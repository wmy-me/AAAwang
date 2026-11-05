"""Owner-scoped task and immutable condition revision operations."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from life_agent.db.models import Conversation, Task, TaskRevision
from life_agent.modules.tasks.consistency import (
    check_goal_consistency,
    resolve_goal,
)
from life_agent.modules.tasks.schemas import Conditions, validate_conditions


class TaskNotFoundError(LookupError):
    """Raised when an owner-scoped conversation or task is unavailable."""


class RevisionConflictError(ValueError):
    def __init__(self, current_revision: int) -> None:
        self.current_revision = current_revision
        super().__init__("task revision conflict")


@dataclass(frozen=True)
class TaskView:
    task: Task
    conditions: Conditions
    goal: str
    goal_conflicts: list[dict[str, object]]
    goal_resolution: str | None
    goal_legacy: bool


def _get_owned_conversation(
    db: Session, owner_id: uuid.UUID, conversation_id: uuid.UUID
) -> Conversation:
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.owner_id == owner_id,
        )
    )
    if conversation is None:
        raise TaskNotFoundError
    return conversation


def _get_owned_task(db: Session, owner_id: uuid.UUID, task_id: uuid.UUID) -> Task:
    task = db.scalar(
        select(Task)
        .join(Conversation)
        .where(Task.id == task_id, Conversation.owner_id == owner_id)
    )
    if task is None:
        raise TaskNotFoundError
    return task


def _get_revision(db: Session, task_id: uuid.UUID, revision: int) -> TaskRevision:
    snapshot = db.scalar(
        select(TaskRevision).where(
            TaskRevision.task_id == task_id,
            TaskRevision.revision == revision,
        )
    )
    if snapshot is None:
        raise TaskNotFoundError
    return snapshot


def create_task(
    db: Session,
    owner_id: uuid.UUID,
    conversation_id: uuid.UUID,
    domain: str,
    goal: str,
    conditions: Conditions,
    change_note: str | None,
) -> TaskView:
    _get_owned_conversation(db, owner_id, conversation_id)
    consistency = check_goal_consistency(goal, conditions)
    task = Task(
        conversation_id=conversation_id,
        domain=domain,
        goal=goal,
        current_revision=1,
        updated_at=datetime.now(UTC),
    )
    db.add(task)
    db.flush()
    db.add(
        TaskRevision(
            task_id=task.id,
            revision=1,
            goal=goal,
            goal_conflicts=consistency.conflicts or None,
            goal_resolution=None,
            goal_legacy=False,
            conditions=conditions,
            change_note=change_note,
            created_at=datetime.now(UTC),
        )
    )
    db.commit()
    db.refresh(task)
    return TaskView(
        task=task,
        conditions=conditions,
        goal=goal,
        goal_conflicts=consistency.conflicts,
        goal_resolution=None,
        goal_legacy=False,
    )


def get_task(db: Session, owner_id: uuid.UUID, task_id: uuid.UUID) -> TaskView:
    task = _get_owned_task(db, owner_id, task_id)
    snapshot = _get_revision(db, task.id, task.current_revision)
    return TaskView(
        task=task,
        conditions=snapshot.conditions,
        goal=snapshot.goal,
        goal_conflicts=(snapshot.goal_conflicts or check_goal_consistency(snapshot.goal, snapshot.conditions).conflicts),
        goal_resolution=snapshot.goal_resolution,
        goal_legacy=snapshot.goal_legacy,
    )


def list_tasks(
    db: Session,
    owner_id: uuid.UUID,
    conversation_id: uuid.UUID,
    offset: int,
    limit: int,
) -> list[TaskView]:
    _get_owned_conversation(db, owner_id, conversation_id)
    tasks = list(
        db.scalars(
            select(Task)
            .where(Task.conversation_id == conversation_id)
            .order_by(Task.updated_at.desc(), Task.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    if not tasks:
        return []
    revisions = {
        (snapshot.task_id, snapshot.revision): snapshot
        for snapshot in db.scalars(
            select(TaskRevision).where(TaskRevision.task_id.in_([task.id for task in tasks]))
        )
    }
    views: list[TaskView] = []
    for task in tasks:
        snapshot = revisions[(task.id, task.current_revision)]
        views.append(
            TaskView(
                task=task,
                conditions=snapshot.conditions,
                goal=snapshot.goal,
                goal_conflicts=(snapshot.goal_conflicts or check_goal_consistency(snapshot.goal, snapshot.conditions).conflicts),
                goal_resolution=snapshot.goal_resolution,
                goal_legacy=snapshot.goal_legacy,
            )
        )
    return views


def list_revisions(
    db: Session, owner_id: uuid.UUID, task_id: uuid.UUID, offset: int, limit: int
) -> list[TaskRevision]:
    _get_owned_task(db, owner_id, task_id)
    return list(
        db.scalars(
            select(TaskRevision)
            .where(TaskRevision.task_id == task_id)
            .order_by(TaskRevision.revision)
            .offset(offset)
            .limit(limit)
        )
    )


def create_revision(
    db: Session,
    owner_id: uuid.UUID,
    task_id: uuid.UUID,
    expected_revision: int,
    goal: str | None,
    conditions: Conditions,
    change_note: str | None,
    confirm_goal_conflict: bool = False,
    commit: bool = True,
) -> TaskRevision:
    task = _get_owned_task(db, owner_id, task_id)
    conditions = validate_conditions(task.domain, conditions)
    current_snapshot = _get_revision(db, task.id, expected_revision)
    effective_goal = (goal or current_snapshot.goal).strip()
    consistency = check_goal_consistency(effective_goal, conditions)
    resolution = None
    if consistency.has_conflict and confirm_goal_conflict:
        effective_goal = resolve_goal(effective_goal, conditions, consistency)
        consistency = check_goal_consistency(effective_goal, conditions)
        resolution = "confirmed_structured_conditions"
    new_revision = expected_revision + 1
    now = datetime.now(UTC)
    result = db.execute(
        update(Task)
        .where(Task.id == task.id, Task.current_revision == expected_revision)
        .values(current_revision=new_revision, updated_at=now)
    )
    if result.rowcount != 1:
        db.rollback()
        current = _get_owned_task(db, owner_id, task_id)
        raise RevisionConflictError(current.current_revision)
    snapshot = TaskRevision(
        task_id=task.id,
        revision=new_revision,
        goal=effective_goal,
        goal_conflicts=consistency.conflicts or None,
        goal_resolution=resolution,
        goal_legacy=False,
        conditions=conditions,
        change_note=change_note,
        created_at=now,
    )
    db.add(snapshot)
    task.goal = effective_goal
    if commit:
        db.commit()
        db.refresh(snapshot)
    return snapshot