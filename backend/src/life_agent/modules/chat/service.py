"""Transactional conversation and selected-task chat turn services."""

import asyncio
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from life_agent.core.config import get_settings
from life_agent.core.llm.deepseek import call_deepseek
from life_agent.db.models import Conversation, Message, Run, Task, TaskRevision
from life_agent.modules.capabilities import route_task_turn
from life_agent.modules.runs.service import create_run
from life_agent.modules.tasks.consistency import (
    GoalConflictError,
    check_goal_consistency,
)
from life_agent.modules.tasks.schemas import Conditions, validate_conditions


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
            Message.client_message_id == f"assistant:{message.id}",
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
            r"买|购买|采购|采买|商品|礼物|奖品|预算|推荐.+(?:买|商品)|找.+(?:店|地点)",
            content,
        )
    )


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
    message = Message(
        conversation_id=conversation.id,
        client_message_id=client_turn_id,
        role="user",
        content=content,
        created_at=datetime.now(UTC),
    )
    db.add(message)
    db.flush()
    if _looks_like_shopping(content):
        task, revision = _new_shopping_task(db, conversation.id, content)
        message.task_id = task.id
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
        message.run_id = run.id
        conversation.updated_at = datetime.now(UTC)
        db.commit()
        db.refresh(message)
        db.refresh(run)
        db.refresh(task)
        return ConversationTurn(message, None, run, task, dict(revision.conditions), True)

    prompt = (
        "你是生活采买助手。请直接、简洁地回答用户消息；普通问候和一般问题不要引导填写表单，"
        "不要声称查询了未调用的工具。未知信息要明确说明。\n用户消息：" + content
    )
    answer = asyncio.run(call_deepseek(get_settings(), prompt)).text[:12_000]
    assistant = Message(
        conversation_id=conversation.id,
        client_message_id=f"assistant:{message.id}",
        role="assistant",
        content=answer,
        created_at=datetime.now(UTC),
    )
    db.add(assistant)
    conversation.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(message)
    db.refresh(assistant)
    return ConversationTurn(message, assistant, None, None, {}, True)


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
