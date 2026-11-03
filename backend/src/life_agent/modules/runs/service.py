"""Owner-scoped run persistence and database-backed worker ownership."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from life_agent.db.models import (
    Conversation,
    Run,
    RunEvent,
    ShoppingRunResult,
    Task,
    TaskRevision,
)

RUN_TERMINAL = {"completed", "failed", "cancelled"}
RUN_EVENT_TYPES = {
    "run.queued",
    "run.running",
    "run.cancel_requested",
    "run.completed",
    "run.failed",
    "run.cancelled",
}


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
    goal: str
    execution_type: str
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


def _lease_expired(lease_until: datetime | None, now: datetime) -> bool:
    if lease_until is None:
        return True
    if lease_until.tzinfo is None:
        lease_until = lease_until.replace(tzinfo=UTC)
    return lease_until <= now


def _owned_run(
    db: Session, owner_id: uuid.UUID, run_id: uuid.UUID, *, for_update: bool = False
) -> Run:
    query = select(Run).where(Run.id == run_id, Run.owner_id == owner_id)
    if for_update:
        query = query.with_for_update()
    run = db.scalar(query)
    if run is None:
        raise RunNotFoundError
    return run


def create_run(
    db: Session,
    owner_id: uuid.UUID,
    task_id: uuid.UUID,
    expected_revision: int,
    idempotency_key: str,
    execution_type: str = "diagnostic",
) -> Run:
    task = db.scalar(
        select(Task)
        .join(Conversation)
        .where(Task.id == task_id, Conversation.owner_id == owner_id)
        .with_for_update()
    )
    if task is None:
        raise RunNotFoundError
    if execution_type not in {"diagnostic", "shopping_research"}:
        raise ValueError("unsupported run execution type")
    if execution_type == "shopping_research" and task.domain != "shopping":
        raise ValueError("shopping execution requires a shopping task")
    existing = db.scalar(
        select(Run).where(Run.task_id == task_id, Run.idempotency_key == idempotency_key)
    )
    if existing is not None:
        if (
            existing.owner_id != owner_id
            or existing.revision != expected_revision
            or existing.execution_type != execution_type
        ):
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
        execution_type=execution_type,
        status="queued",
        attempt=0,
        fencing_token=0,
        cancel_requested=False,
    )
    db.add(run)
    db.flush()
    _append_event(db, run, "run.queued", datetime.now(UTC))
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
    run = _owned_run(db, owner_id, run_id, for_update=True)
    now = datetime.now(UTC)
    if run.status == "queued":
        run.status = "cancelled"
        run.finished_at = now
        run.cancel_requested = True
        _append_event(db, run, "run.cancelled", now)
    elif run.status == "running":
        if not run.cancel_requested:
            run.cancel_requested = True
            _append_event(db, run, "run.cancel_requested", now)
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
        _append_event(db, run, "run.cancelled", now)
        db.commit()
        return None
    run.status = "running"
    run.worker_id = worker_id
    run.lease_until = now + timedelta(seconds=lease_seconds)
    run.started_at = run.started_at or now
    run.attempt += 1
    run.fencing_token += 1
    _append_event(db, run, "run.running", now)
    db.commit()
    return RunClaim(
        run_id=run.id,
        task_id=run.task_id,
        task_revision_id=run.task_revision_id,
        revision=run.revision,
        conditions=dict(run.conditions),
        goal=run.task.goal,
        execution_type=run.execution_type,
        worker_id=worker_id,
        fencing_token=run.fencing_token,
    )


def _finish_claim(
    db: Session,
    claim: RunClaim,
    status: str,
    diagnostic: dict[str, object] | None = None,
    error_summary: str | None = None,
    shopping_result: dict[str, object] | None = None,
) -> bool:
    now = datetime.now(UTC)
    run = db.scalar(select(Run).where(Run.id == claim.run_id).with_for_update())
    if (
        run is None
        or run.status != "running"
        or run.worker_id != claim.worker_id
        or run.fencing_token != claim.fencing_token
        or _lease_expired(run.lease_until, now)
    ):
        db.rollback()
        return False
    run.status = status
    run.finished_at = now
    run.lease_until = None
    run.diagnostic = diagnostic
    run.error_summary = error_summary
    if shopping_result is not None:
        db.add(
            ShoppingRunResult(
                run_id=run.id,
                answer=str(shopping_result["answer"]),
                source=dict(shopping_result["source"]),
                execution_version=str(shopping_result["execution_version"]),
            )
        )
    _append_event(db, run, f"run.{status}", now)
    db.commit()
    return True


def complete_claim(
    db: Session,
    claim: RunClaim,
    diagnostic: dict[str, object] | None = None,
    shopping_result: dict[str, object] | None = None,
) -> bool:
    return _finish_claim(
        db,
        claim,
        "completed",
        diagnostic=diagnostic,
        shopping_result=shopping_result,
    )


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


def renew_claim(db: Session, claim: RunClaim, lease_seconds: int) -> bool:
    now = datetime.now(UTC)
    run = db.scalar(select(Run).where(Run.id == claim.run_id).with_for_update())
    if (
        run is None
        or run.status != "running"
        or run.worker_id != claim.worker_id
        or run.fencing_token != claim.fencing_token
        or _lease_expired(run.lease_until, now)
    ):
        db.rollback()
        return False
    run.lease_until = now + timedelta(seconds=lease_seconds)
    db.commit()
    return True


def fail_exhausted_runs(db: Session, max_attempts: int) -> int:
    now = datetime.now(UTC)
    runs = list(
        db.scalars(
            select(Run)
            .where(
                Run.status == "running",
                Run.lease_until <= now,
                Run.attempt >= max_attempts,
            )
            .with_for_update(skip_locked=True)
        )
    )
    for run in runs:
        run.status = "failed"
        run.finished_at = now
        run.lease_until = None
        run.error_summary = "worker lease expired after maximum attempts"
        _append_event(db, run, "run.failed", now)
    db.commit()
    return len(runs)


def _append_event(db: Session, run: Run, event_type: str, occurred_at: datetime) -> RunEvent:
    if event_type not in RUN_EVENT_TYPES:
        raise ValueError(f"unsupported run event: {event_type}")
    sequence = db.scalar(
        select(func.coalesce(func.max(RunEvent.sequence), 0)).where(
            RunEvent.run_id == run.id
        )
    ) + 1
    payload: dict[str, object] = {
        "run_id": str(run.id),
        "status": run.status,
        "revision": run.revision,
        "occurred_at": occurred_at.isoformat(),
    }
    if run.diagnostic is not None:
        payload["diagnostic"] = run.diagnostic
    if run.error_summary is not None:
        payload["error_summary"] = run.error_summary
    event = RunEvent(
        run_id=run.id,
        sequence=sequence,
        event_type=event_type,
        occurred_at=occurred_at,
        payload=payload,
    )
    db.add(event)
    return event


def list_events(
    db: Session, owner_id: uuid.UUID, run_id: uuid.UUID, after: int, limit: int
) -> list[RunEvent]:
    _owned_run(db, owner_id, run_id)
    return list(
        db.scalars(
            select(RunEvent)
            .where(RunEvent.run_id == run_id, RunEvent.sequence > after)
            .order_by(RunEvent.sequence)
            .limit(limit)
        )
    )


def get_event_cursor(db: Session, run_id: uuid.UUID) -> int:
    return db.scalar(
        select(func.coalesce(func.max(RunEvent.sequence), 0)).where(
            RunEvent.run_id == run_id
        )
    )


def get_shopping_result(
    db: Session, owner_id: uuid.UUID, run_id: uuid.UUID
) -> ShoppingRunResult:
    run = _owned_run(db, owner_id, run_id)
    if run.execution_type != "shopping_research":
        raise RunNotFoundError
    result = db.scalar(
        select(ShoppingRunResult).where(ShoppingRunResult.run_id == run_id)
    )
    if result is None:
        raise RunNotFoundError
    return result