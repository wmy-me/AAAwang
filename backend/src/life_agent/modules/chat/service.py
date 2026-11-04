"""Transactional selected-task chat turn creation and idempotent lookup."""

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from life_agent.db.models import Conversation, Message, Run, Task, TaskRevision
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
    people = re.search(_INT_PATTERN + r"\s*(?:人|位|名)", content)
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
    map_request = bool(re.search(r"(地点|门店|店铺|超市|商场|附近|位置|地图|哪里买)", content))
    run = create_run(
        db,
        owner_id,
        task.id,
        expected_revision,
        f"turn:{client_turn_id}",
        "map_places" if map_request else "shopping_agent",
        input_message_id=message.id,
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
