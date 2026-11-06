"""Transactional conversation and selected-task chat turn services."""

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from life_agent.core.config import get_settings
from life_agent.db.models import Conversation, Message, Run, Task, TaskRevision
from life_agent.modules.capabilities import route_task_turn
from life_agent.modules.chat.context import ContextBuilder
from life_agent.modules.runs.service import create_run
from life_agent.modules.tasks.consistency import (
    GoalConflictError,
    check_goal_consistency,
)
from life_agent.modules.tasks.schemas import Conditions, validate_conditions
from life_agent.modules.tasks.service import create_revision


class ChatTurnNotFoundError(LookupError):
    """The selected conversation or task is not owned by the caller."""


class ChatTurnConflictError(ValueError):
    """The client turn key or expected task revision conflicts."""


@dataclass(frozen=True)
class ConversationTurn:
    message: Message
    assistant_message: Message | None
    run: Run | None
    task: Task | None
    conditions: Conditions
    created: bool


@dataclass(frozen=True)
class ChatTurn:
    message: Message
    run: object
    task: Task
    conditions: Conditions
    goal: str
    goal_conflicts: list[dict[str, object]]
    goal_resolution: str | None
    goal_legacy: bool
    assistant_message: Message | None
    created: bool


_INT_PATTERN = r"(?<!\d)(\d{1,6})"


def _owned_conversation(
    db: Session, owner_id: uuid.UUID, conversation_id: uuid.UUID
) -> Conversation:
    conversation = db.scalar(
        select(Conversation)
        .where(Conversation.id == conversation_id, Conversation.owner_id == owner_id)
        .with_for_update()
    )
    if conversation is None:
        raise ChatTurnNotFoundError
    return conversation


def _conversation_turn_existing(
    db: Session,
    owner_id: uuid.UUID,
    conversation_id: uuid.UUID,
    client_turn_id: str,
    content: str,
) -> ConversationTurn | None:
    message = db.scalar(
        select(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Message.conversation_id == conversation_id,
            Message.client_message_id == client_turn_id,
            Conversation.owner_id == owner_id,
        )
    )
    if message is None:
        return None
    if message.role != "user" or message.content != content:
        raise ChatTurnConflictError
    run = db.get(Run, message.run_id) if message.run_id is not None else None
    assistant = db.scalar(
        select(Message).where(
            Message.conversation_id == conversation_id,
            Message.run_id == run.id if run is not None else False,
            Message.role == "assistant",
        )
    )
    task = db.get(Task, message.task_id) if message.task_id is not None else None
    conditions = {}
    if task is not None:
        snapshot = db.scalar(
            select(TaskRevision).where(
                TaskRevision.task_id == task.id,
                TaskRevision.revision == task.current_revision,
            )
        )
        conditions = dict(snapshot.conditions) if snapshot is not None else {}
    return ConversationTurn(message, assistant, run, task, conditions, False)


def _looks_like_shopping(content: str) -> bool:
    return bool(
        re.search(
            r"买|购买|采购|采买|商品|礼物|预算|推荐.+(?:买|商品)|找.+(?:店|地点)",
            content,
        )
    )


def _budget_update(content: str) -> int | None:
    match = re.search(r"预算\s*(?:改为|改成|调整为|变为|设为|增加到|降到)?\s*(\d{1,6})\s*元", content)
    return int(match.group(1)) if match else None


def _new_shopping_task(
    db: Session, conversation_id: uuid.UUID, content: str
) -> tuple[Task, TaskRevision]:
    now = datetime.now(UTC)
    task = Task(
        conversation_id=conversation_id,
        domain="shopping",
        goal=content[:500],
        current_revision=1,
        updated_at=now,
    )
    db.add(task)
    db.flush()
    revision = TaskRevision(
        task_id=task.id,
        revision=1,
        goal=content[:500],
        goal_conflicts=None,
        goal_resolution=None,
        goal_legacy=False,
        conditions=_infer_conditions(content, {}, None),
        change_note="由纯对话入口自动创建",
        created_at=now,
    )
    db.add(revision)
    db.flush()
    return task, revision


def _conversation_history(db: Session, conversation_id: uuid.UUID) -> list[dict[str, str]]:
    messages = list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(8)
        )
    )
    return [
        {"role": message.role, "content": message.content}
        for message in reversed(messages)
    ]


def _bounded_history(
    db: Session, owner_id: uuid.UUID, conversation_id: uuid.UUID
) -> list[dict[str, str]]:
    settings = get_settings()
    context = ContextBuilder(
        max_messages=settings.conversation_context_max_messages,
        max_characters=settings.conversation_context_max_characters,
    ).build(db, owner_id, conversation_id)
    return [{"role": item.role, "content": item.content} for item in context.messages]


def _conversation_tasks(
    db: Session, conversation_id: uuid.UUID
) -> list[Task]:
    return list(
        db.scalars(
            select(Task)
            .where(Task.conversation_id == conversation_id)
            .order_by(Task.updated_at.desc(), Task.id.desc())
        )
    )


def _explicit_task_reference(content: str, tasks: list[Task]) -> bool:
    lowered = content.casefold()
    return any(
        str(task.id).casefold() in lowered or task.goal.casefold() in lowered
        for task in tasks
    )


def _task_snapshot(db: Session, task: Task) -> TaskRevision:
    snapshot = db.scalar(
        select(TaskRevision).where(
            TaskRevision.task_id == task.id,
            TaskRevision.revision == task.current_revision,
        )
    )
    if snapshot is None:
        raise ChatTurnConflictError
    return snapshot


def _taskless_conversation_run(
    db: Session,
    owner_id: uuid.UUID,
    conversation: Conversation,
    message: Message,
    client_turn_id: str,
    decision: dict[str, object] | None = None,
) -> ConversationTurn:
    run = create_run(
        db,
        owner_id,
        None,
        None,
        f"conversation:{client_turn_id}",
        "direct_answer",
        input_message_id=message.id,
        decision=decision,
        commit=False,
    )
    message.run_id = run.id
    conversation.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(message)
    db.refresh(run)
    return ConversationTurn(message, None, run, None, {}, True)


def _task_conversation_run(
    db: Session,
    owner_id: uuid.UUID,
    conversation: Conversation,
    message: Message,
    client_turn_id: str,
    task: Task,
    revision: TaskRevision,
) -> ConversationTurn:
    run = create_run(
        db,
        owner_id,
        task.id,
        revision.revision,
        f"conversation:{client_turn_id}",
        "capability_decision",
        input_message_id=message.id,
        decision={
            "kind": "pending",
            "capability_ids": [],
            "decision_source": "deepseek_structured_worker",
        },
        commit=False,
    )
    message.task_id = task.id
    message.run_id = run.id
    conversation.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(message)
    db.refresh(run)
    db.refresh(task)
    return ConversationTurn(message, None, run, task, dict(revision.conditions), True)


def _clarification_decision(text: str) -> dict[str, object]:
    return {
        "kind": "clarification",
        "capability_ids": [],
        "clarification": text[:500],
        "decision_source": "deepseek_structured_worker",
    }


def submit_conversation_turn(
    db: Session,
    owner_id: uuid.UUID,
    conversation_id: uuid.UUID,
    client_turn_id: str,
    content: str,
) -> ConversationTurn:
    existing = _conversation_turn_existing(
        db, owner_id, conversation_id, client_turn_id, content
    )
    if existing is not None:
        return existing
    conversation = _owned_conversation(db, owner_id, conversation_id)
    # Routing is deliberately deferred to the Worker.  The API transaction only
    # persists the idempotent user turn and a cancellable durable Run.
    message = Message(
        conversation_id=conversation.id,
        client_message_id=client_turn_id,
        role="user",
        content=content,
        created_at=datetime.now(UTC),
    )
    db.add(message)
    db.flush()
    run = create_run(
        db, owner_id, None, None, f"conversation:{client_turn_id}",
        "conversation_route", input_message_id=message.id,
        decision={"kind": "pending", "capability_ids": []}, commit=False,
    )
    message.run_id = run.id
    conversation.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(message)
    db.refresh(run)
    return ConversationTurn(message, None, run, None, {}, True)


def conversation_route_inputs(
    db: Session, owner_id: uuid.UUID, conversation_id: uuid.UUID
) -> list[dict[str, object]]:
    return [
        {"id": str(task.id), "goal": task.goal, "revision": task.current_revision, "domain": task.domain}
        for task in _conversation_tasks(db, conversation_id)
    ]


def apply_conversation_route(db: Session, claim, classification: dict[str, object], budget: dict[str, object]):
    """Bind a claimed route Run to its safe task/revision after model routing.

    This runs after the network call, holds the row lock only while mutating
    trusted database state, and never accepts a model-provided owner or revision.
    """
    run = db.scalar(select(Run).where(Run.id == claim.run_id).with_for_update())
    message = db.scalar(select(Message).where(Message.id == claim.input_message_id).with_for_update())
    if run is None or message is None or run.owner_id != claim.owner_id:
        raise ChatTurnNotFoundError
    run.budget = budget
    conversation = _owned_conversation(db, claim.owner_id, run.conversation_id)
    tasks = _conversation_tasks(db, conversation.id)
    content = message.content
    if (
        len(tasks) > 1
        and classification.get("task_id")
        and classification.get("intent") in {"task", "update_task"}
        and not _explicit_task_reference(content, tasks)
    ):
        classification = {
            **classification,
            "intent": "ambiguous",
            "task_id": None,
            "clarification": "当前对话关联了多个任务。请说明要修改哪个任务，或提供任务名称。",
        }
    budget_update = _budget_update(content)
    if budget_update is not None and classification.get("intent") == "task":
        if len(tasks) == 1:
            classification = {
                **classification,
                "intent": "update_task",
                "task_id": str(tasks[0].id),
            }
        elif len(tasks) > 1:
            classification = {
                **classification,
                "intent": "ambiguous",
                "task_id": None,
                "clarification": "当前对话关联了多个任务，请说明要修改哪一个的预算。",
            }
    intent = classification.get("intent")
    if intent == "ambiguous":
        return _bind_routed_direct(db, claim, run, _clarification_decision(str(classification.get("clarification") or "请说明你想继续哪个任务或补充目标。")))
    if intent == "chat":
        return _bind_routed_direct(db, claim, run, {"kind": "direct", "capability_ids": []})
    if intent == "memory":
        action = classification.get("memory_action")
        if action not in {"remember", "list", "update", "forget"}:
            return _bind_routed_direct(db, claim, run, _clarification_decision("请明确说明要记住、查看、修改或忘记哪项普通偏好。"))
        decision = {
            "kind": "memory",
            "capability_ids": [],
            "memory_action": action,
            "memory_category": classification.get("memory_category"),
            "memory_key": classification.get("memory_key"),
            "memory_value": classification.get("memory_value"),
            "decision_source": "deepseek_structured_worker",
        }
        return _bind_routed_direct(db, claim, run, decision)
    if intent == "update_task":
        selected = [
            task
            for task in tasks
            if str(task.id) == classification.get("task_id")
        ]
        if not selected and len(tasks) == 1:
            selected = tasks
        if len(selected) != 1 or selected[0].domain != "shopping":
            return _bind_routed_direct(db, claim, run, _clarification_decision("我无法安全确定要修改哪个任务，请说明任务名称或重新描述目标。"))
        task = selected[0]
        current = _task_snapshot(db, task)
        conditions = dict(current.conditions)
        if budget_update is not None:
            conditions["budget"] = budget_update
        else:
            conditions = _infer_conditions(
                content, conditions, _latest_assistant(db, task.id)
            )
        if conditions == current.conditions:
            return _bind_routed_direct(db, claim, run, _clarification_decision("我没有识别到要修改的条件，请直接说明新的预算、人数或数量。"))
        revision = create_revision(
            db, claim.owner_id,
            task.id,
            task.current_revision,
            None,
            conditions,
            "由会话自然语言更新条件",
            confirm_goal_conflict=True,
            commit=False,
        )
        return _bind_routed_task(db, claim, run, message, task, revision)
    if intent == "task":
        selected = [
            task
            for task in tasks
            if str(task.id) == classification.get("task_id")
        ]
        if len(selected) == 1 and selected[0].domain == "shopping":
            task = selected[0]
            current = _task_snapshot(db, task)
            conditions = _infer_conditions(
                content, dict(current.conditions), _latest_assistant(db, task.id)
            )
            revision = current
            if conditions != current.conditions:
                revision = create_revision(
                    db, claim.owner_id,
                    task.id,
                    task.current_revision,
                    None,
                    conditions,
                    "由会话自然语言补充条件",
                    confirm_goal_conflict=True,
                    commit=False,
                )
            return _bind_routed_task(db, claim, run, message, task, revision)
        task, revision = _new_shopping_task(db, conversation.id, content)
        return _bind_routed_task(db, claim, run, message, task, revision)
    return _bind_routed_direct(db, claim, run, {"kind": "direct", "capability_ids": []})


def _bind_routed_direct(db: Session, claim, run: Run, decision: dict[str, object]):
    run.execution_type = "direct_answer"
    run.decision = decision
    db.commit()
    return claim.__class__(**{**claim.__dict__, "execution_type": "direct_answer", "decision": decision})


def _bind_routed_task(db: Session, claim, run: Run, message: Message, task: Task, revision: TaskRevision):
    run.task_id = task.id
    run.task_revision_id = revision.id
    run.revision = revision.revision
    run.goal = revision.goal
    run.conditions = dict(revision.conditions)
    run.execution_type = "capability_decision"
    run.decision = {"kind": "pending", "capability_ids": [], "decision_source": "deepseek_structured_worker"}
    message.task_id = task.id
    db.commit()
    return claim.__class__(**{**claim.__dict__, "task_id": task.id, "task_revision_id": revision.id, "revision": revision.revision, "goal": revision.goal, "conditions": dict(revision.conditions), "execution_type": "capability_decision", "decision": dict(run.decision)})


def _owned_task(
    db: Session, owner_id: uuid.UUID, conversation_id: uuid.UUID, task_id: uuid.UUID
) -> Task:
    task = db.scalar(
        select(Task)
        .join(Conversation)
        .where(
            Task.id == task_id,
            Task.conversation_id == conversation_id,
            Conversation.owner_id == owner_id,
        )
        .with_for_update()
    )
    if task is None or task.domain != "shopping":
        raise ChatTurnNotFoundError
    return task


def _existing_turn(
    db: Session,
    owner_id: uuid.UUID,
    conversation_id: uuid.UUID,
    client_turn_id: str,
    content: str,
    task_id: uuid.UUID,
) -> ChatTurn | None:
    message = db.scalar(
        select(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Message.conversation_id == conversation_id,
            Message.client_message_id == client_turn_id,
            Conversation.owner_id == owner_id,
        )
    )
    if message is None:
        return None
    if (
        message.content != content
        or message.task_id != task_id
        or message.role != "user"
    ):
        raise ChatTurnConflictError
    if message.run_id is None:
        raise ChatTurnConflictError
    run = db.get(Run, message.run_id)
    if run is None:
        raise ChatTurnConflictError
    task = db.get(Task, task_id)
    if task is None:
        raise ChatTurnNotFoundError
    snapshot = db.scalar(
        select(TaskRevision).where(
            TaskRevision.task_id == task.id,
            TaskRevision.revision == run.revision,
        )
    )
    if snapshot is None:
        raise ChatTurnConflictError
    assistant = db.scalar(select(Message).where(Message.run_id == run.id, Message.role == "assistant"))
    return ChatTurn(
        message=message,
        run=run,
        task=task,
        conditions=dict(snapshot.conditions),
        goal=snapshot.goal,
        goal_conflicts=check_goal_consistency(snapshot.goal, snapshot.conditions).conflicts,
        goal_resolution=snapshot.goal_resolution,
        goal_legacy=snapshot.goal_legacy,
        assistant_message=assistant,
        created=False,
    )


def _latest_assistant(db: Session, task_id: uuid.UUID) -> Message | None:
    return db.scalar(
        select(Message)
        .where(Message.task_id == task_id, Message.role == "assistant")
        .order_by(Message.created_at.desc(), Message.id.desc())
    )


def _infer_conditions(
    content: str, current: Conditions, previous_assistant: Message | None
) -> Conditions:
    updates: Conditions = {}
    people = re.search(_INT_PATTERN + r"\s*(?:人|位|名|个\s*学生|名\s*学生)", content)
    if people is None and previous_assistant is not None and "人数" in previous_assistant.content:
        people = re.fullmatch(r"\s*" + _INT_PATTERN + r"\s*(?:人|位|名)?\s*", content)
    if people is not None:
        updates["people"] = int(people.group(1))

    budget = re.search(r"(?:预算|不超过|最多|限额)\s*[¥￥]?\s*(\d+(?:\.\d+)?)", content)
    if budget is not None:
        updates["budget"] = float(budget.group(1))

    quantity = re.search(_INT_PATTERN + r"\s*(?:件|盒|套|份|个)", content)
    if quantity is not None:
        updates["quantity"] = int(quantity.group(1))

    item = re.search(r"(?:物品|商品|买|购买)\s*[:：]?\s*([^，。；;\n]{2,80})", content)
    if item is not None and item.group(1).strip() not in {"东西", "商品"}:
        updates["item"] = item.group(1).strip()

    merged = dict(current)
    merged.update(updates)
    return validate_conditions("shopping", merged)


def _is_map_request(content: str) -> bool:
    """Keep the legacy routing helper for old callers and focused tests."""
    decision = route_task_turn(content)
    return "map_place_search" in decision.capability_ids or (
        decision.clarification is not None
        and "城市或位置范围" in decision.clarification
    )


def submit_turn(
    db: Session,
    owner_id: uuid.UUID,
    conversation_id: uuid.UUID,
    client_turn_id: str,
    content: str,
    task_id: uuid.UUID,
    expected_revision: int,
) -> ChatTurn:
    existing = _existing_turn(db, owner_id, conversation_id, client_turn_id, content, task_id)
    if existing is not None:
        return existing

    task = _owned_task(db, owner_id, conversation_id, task_id)
    if task.current_revision != expected_revision:
        raise ChatTurnConflictError
    snapshot = db.scalar(
        select(TaskRevision).where(
            TaskRevision.task_id == task.id,
            TaskRevision.revision == expected_revision,
        )
    )
    if snapshot is None:
        raise ChatTurnNotFoundError
    current = dict(snapshot.conditions)
    conditions = _infer_conditions(content, current, _latest_assistant(db, task.id))
    consistency = check_goal_consistency(snapshot.goal, conditions)
    if consistency.has_conflict:
        raise GoalConflictError(consistency.conflicts)
    if conditions != current:
        now = datetime.now(UTC)
        new_revision = expected_revision + 1
        updated = db.execute(
            update(Task)
            .where(Task.id == task.id, Task.current_revision == expected_revision)
            .values(current_revision=new_revision, updated_at=now)
        )
        if updated.rowcount != 1:
            raise ChatTurnConflictError
        snapshot = TaskRevision(
            task_id=task.id,
            revision=new_revision,
            goal=snapshot.goal,
            goal_conflicts=None,
            goal_resolution=None,
            goal_legacy=False,
            conditions=conditions,
            change_note="通过购物任务对话补充条件",
            created_at=now,
        )
        db.add(snapshot)
        db.flush()
        task.current_revision = new_revision
        expected_revision = new_revision

    message = Message(
        conversation_id=conversation_id,
        client_message_id=client_turn_id,
        role="user",
        content=content,
        task_id=task.id,
        created_at=datetime.now(UTC),
    )
    db.add(message)
    db.flush()
    capability_ids: list[str] = []
    decision_snapshot: dict[str, object] = {
        "kind": "pending",
        "capability_ids": [],
        "decision_source": "deepseek_structured_worker",
    }
    run = create_run(
        db,
        owner_id,
        task.id,
        expected_revision,
        f"turn:{client_turn_id}",
        "capability_decision",
        input_message_id=message.id,
        capability_ids=capability_ids,
        decision=decision_snapshot,
        commit=False,
    )
    message.run_id = run.id
    conversation = db.get(Conversation, conversation_id)
    if conversation is not None:
        conversation.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(message)
    db.refresh(run)
    db.refresh(task)
    return ChatTurn(
        message=message,
        run=run,
        task=task,
        conditions=conditions,
        goal=snapshot.goal,
        goal_conflicts=[],
        goal_resolution=snapshot.goal_resolution,
        goal_legacy=snapshot.goal_legacy,
        assistant_message=None,
        created=True,
    )
