"""Owner-scoped run persistence and database-backed worker ownership."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from life_agent.db.models import Conversation, Run, Task, TaskRevision

RUN_TERMINAL = {"completed", "failed", "cancelled"}


class RunNotFoundError(LookupError):
    """Raised when an owner-scoped task or run is unavailable."""


class RunRevisionConflictError(ValueError):
    def __init__(self, current_revision: int) -> None:
        self.current_revision = current_revision
        super().__init__("task revision conflict")


class IdempotencyConflictError(ValueError):
    """Raised when a key is already associated with another request."""


@dataclass(frozen=True)
class RunClaim:
    run_id: uuid.UUID
    task_id: uuid.UUID
    task_revision_id: uuid.UUID
    revision: int
    conditions: dict[str, object]
    worker_id: str
    fencing_token: int


def _owned_task(db: Session, owner_id: uuid.UUID, task_id: uuid.UUID) -> Task:
    task = db.scalar(
        select(Task)
        .join(Conversation)
        .where(Task.id == task_id, Conversation.owner_id == owner_id)
    )
    if task is None:
        raise RunNotFoundError
    return task


def _owned_run(db: Session, owner_id: uuid.UUID, run_id: uuid.UUID) -> Run:
    run = db.scalar(select(Run).where(Run.id == run_id, Run.owner_id == owner_id))
    if run is None:
        raise RunNotFoundError
    return run


def create_run(
    db: Session,
    owner_id: uuid.UUID,
    task_id: uuid.UUID,
    expected_revision: int,
    idempotency_key: str,
) -> Run:
    task = db.scalar(
        select(Task)
        .join(Conversation)
        .where(Task.id == task_id, Conversation.owner_id == owner_id)
        .with_for_update()
    )
    if task is None:
        raise RunNotFoundError
    existing = db.scalar(
        select(Run).where(Run.task_id == task_id, Run.idempotency_key == idempotency_key)
    )
    if existing is not None:
        if existing.owner_id != owner_id or existing.revision != expected_revision:
            raise IdempotencyConflictError
        return existing
    if task.current_revision != expected_revision:
        raise RunRevisionConflictError(task.current_revision)
    snapshot = db.scalar(
        select(TaskRevision).where(
            TaskRevision.task_id == task.id,
            TaskRevision.revision == expected_revision,
        )
    )
    if snapshot is None:
        raise RunNotFoundError
    run = Run(
        task_id=task.id,
        owner_id=owner_id,
        task_revision_id=snapshot.id,
        revision=snapshot.revision,
        conditions=dict(snapshot.conditions),
        idempotency_key=idempotency_key,
        status="queued",
        attempt=0,
        fencing_token=0,
        cancel_requested=False,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def get_run(db: Session, owner_id: uuid.UUID, run_id: uuid.UUID) -> Run:
    return _owned_run(db, owner_id, run_id)


def list_runs(
    db: Session, owner_id: uuid.UUID, task_id: uuid.UUID, offset: int, limit: int
) -> list[Run]:
    _owned_task(db, owner_id, task_id)
    return list(
        db.scalars(
            select(Run)
            .where(Run.owner_id == owner_id, Run.task_id == task_id)
            .order_by(Run.created_at.desc(), Run.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )


def cancel_run(db: Session, owner_id: uuid.UUID, run_id: uuid.UUID) -> Run:
    run = _owned_run(db, owner_id, run_id)
    now = datetime.now(UTC)
    if run.status == "queued":
        run.status = "cancelled"
        run.finished_at = now
        run.cancel_requested = True
    elif run.status == "running":
        run.cancel_requested = True
    db.commit()
    db.refresh(run)
    return run


def claim_run(
    db: Session,
    worker_id: str,
    lease_seconds: int,
    max_attempts: int,
) -> RunClaim | None:
    now = datetime.now(UTC)
    run = db.scalar(
        select(Run)
        .where(
            or_(
                Run.status == "queued",
                (Run.status == "running") & (Run.lease_until <= now),
            ),
            Run.attempt < max_attempts,
        )
        .order_by(Run.created_at, Run.id)
        .with_for_update(skip_locked=True)
    )
    if run is None:
        db.rollback()
        return None
    if run.cancel_requested:
        run.status = "cancelled"
        run.finished_at = now
        db.commit()
        return None
    run.status = "running"
    run.worker_id = worker_id
    run.lease_until = now + timedelta(seconds=lease_seconds)
    run.started_at = run.started_at or now
    run.attempt += 1
    run.fencing_token += 1
    db.commit()
    return RunClaim(
        run_id=run.id,
        task_id=run.task_id,
        task_revision_id=run.task_revision_id,
        revision=run.revision,
        conditions=dict(run.conditions),
        worker_id=worker_id,
        fencing_token=run.fencing_token,
    )


def _finish_claim(
    db: Session,
    claim: RunClaim,
    status: str,
    diagnostic: dict[str, object] | None = None,
    error_summary: str | None = None,
) -> bool:
    now = datetime.now(UTC)
    result = db.execute(
        update(Run)
        .where(
            Run.id == claim.run_id,
            Run.status == "running",
            Run.worker_id == claim.worker_id,
            Run.fencing_token == claim.fencing_token,
            Run.lease_until > now,
        )
        .values(
            status=status,
            finished_at=now,
            lease_until=None,
            diagnostic=diagnostic,
            error_summary=error_summary,
        )
    )
    db.commit()
    return result.rowcount == 1


def complete_claim(
    db: Session, claim: RunClaim, diagnostic: dict[str, object]
) -> bool:
    return _finish_claim(db, claim, "completed", diagnostic=diagnostic)


def fail_claim(db: Session, claim: RunClaim, error_summary: str) -> bool:
    return _finish_claim(db, claim, "failed", error_summary=error_summary[:500])


def cancel_claim(db: Session, claim: RunClaim) -> bool:
    return _finish_claim(
        db,
        claim,
        "cancelled",
        diagnostic={"message": "run cancelled at worker checkpoint"},
    )


def is_cancel_requested(db: Session, claim: RunClaim) -> bool:
    run = db.scalar(select(Run).where(Run.id == claim.run_id))
    return run is None or run.cancel_requested


def fail_exhausted_runs(db: Session, max_attempts: int) -> int:
    result = db.execute(
        update(Run)
        .where(
            Run.status == "running",
            Run.lease_until <= datetime.now(UTC),
            Run.attempt >= max_attempts,
        )
        .values(
            status="failed",
            finished_at=datetime.now(UTC),
            lease_until=None,
            error_summary="worker lease expired after maximum attempts",
        )
    )
    db.commit()
    return result.rowcount