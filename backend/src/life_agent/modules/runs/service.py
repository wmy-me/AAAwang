"""Owner-scoped run persistence and database-backed worker ownership."""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from life_agent.db.models import (
    Conversation,
    MapPlace,
    Message,
    Run,
    RunEvent,
    ShoppingCandidate,
    ShoppingPlan,
    ShoppingPlanItem,
    ShoppingRunResult,
    Task,
    TaskRevision,
)
from life_agent.modules.tasks.consistency import (
    GoalConflictError,
    check_goal_consistency,
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
    input_message: str | None
    execution_type: str
    capability_ids: tuple[str, ...]
    decision: dict[str, object] | None
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
    capability_ids: list[str] | tuple[str, ...] | None = None,
    decision: dict[str, object] | None = None,
    input_message_id: uuid.UUID | None = None,
    commit: bool = True,
) -> Run:
    task = db.scalar(
        select(Task)
        .join(Conversation)
        .where(Task.id == task_id, Conversation.owner_id == owner_id)
        .with_for_update()
    )
    if task is None:
        raise RunNotFoundError
    if execution_type not in {
        "diagnostic",
        "direct_answer",
        "shopping_research",
        "shopping_agent",
        "map_places",
        "capability_router",
    }:
        raise ValueError("unsupported run execution type")
    if execution_type in {
        "shopping_research",
        "shopping_agent",
        "map_places",
        "capability_router",
    } and task.domain != "shopping":
        raise ValueError("shopping execution requires a shopping task")
    existing = db.scalar(
        select(Run).where(Run.task_id == task_id, Run.idempotency_key == idempotency_key)
    )
    if existing is not None:
        if (
            existing.owner_id != owner_id
            or existing.revision != expected_revision
            or existing.execution_type != execution_type
            or tuple(existing.capability_ids or ())
            != tuple(capability_ids or ())
            or (existing.decision or None) != (decision or None)
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
    consistency = check_goal_consistency(snapshot.goal, snapshot.conditions)
    if consistency.has_conflict:
        raise GoalConflictError(consistency.conflicts)
    run = Run(
        task_id=task.id,
        owner_id=owner_id,
        task_revision_id=snapshot.id,
        revision=snapshot.revision,
        goal=snapshot.goal,
        conditions=dict(snapshot.conditions),
        idempotency_key=idempotency_key,
        input_message_id=input_message_id,
        execution_type=execution_type,
        capability_ids=list(capability_ids) if capability_ids is not None else None,
        decision=decision,
        budget=None,
        status="queued",
        attempt=0,
        fencing_token=0,
        cancel_requested=False,
    )
    db.add(run)
    db.flush()
    _append_event(db, run, "run.queued", datetime.now(UTC))
    if commit:
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
    goal = run.goal
    input_message = (
        db.scalar(select(Message.content).where(Message.id == run.input_message_id))
        if run.input_message_id is not None
        else None
    )
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
        goal=goal,
        input_message=input_message,
        execution_type=run.execution_type,
        capability_ids=tuple(run.capability_ids or ()),
        decision=dict(run.decision) if run.decision is not None else None,
        worker_id=worker_id,
        fencing_token=run.fencing_token,
    )


def _map_source(shopping_result: dict[str, object]) -> dict[str, object]:
    """Keep map attribution separate from a combined shopping result."""
    source = shopping_result.get("map_source")
    if isinstance(source, dict):
        return source
    return dict(shopping_result.get("source", {}))


def _finish_claim(
    db: Session,
    claim: RunClaim,
    status: str,
    diagnostic: dict[str, object] | None = None,
    error_summary: str | None = None,
    shopping_result: dict[str, object] | None = None,
    shopping_artifacts: dict[str, object] | None = None,
    budget: dict[str, object] | None = None,
    decision: dict[str, object] | None = None,
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
    if budget is not None:
        run.budget = budget
    if decision is not None:
        run.decision = decision
    if shopping_result is not None:
        db.add(
            ShoppingRunResult(
                run_id=run.id,
                answer=str(shopping_result["answer"]),
                source=dict(shopping_result["source"]),
                execution_version=str(shopping_result["execution_version"]),
                decision_type=str(shopping_result.get("decision_type", "delegated_discovery")),
                delegated=bool(shopping_result.get("delegated", False)),
                mcp_call_count=int(shopping_result.get("mcp_call_count", 0)),
            )
        )
        if run.input_message_id is not None:
            input_message = db.scalar(
                select(Message).where(Message.id == run.input_message_id)
            )
            if input_message is not None:
                db.add(
                    Message(
                        conversation_id=input_message.conversation_id,
                        client_message_id=f"assistant:{run.id}",
                        role="assistant",
                        content=str(shopping_result["answer"]),
                        task_id=run.task_id,
                        run_id=run.id,
                    )
                )
        if run.execution_type == "map_places" or shopping_result.get("places") is not None:
            query = str(shopping_result.get("query", ""))[:120]
            city = str(shopping_result.get("city", ""))[:120]
            observed_at = datetime.fromisoformat(
                str(shopping_result.get("observed_at", now.isoformat()))
            )
            source = _map_source(shopping_result)
            for place in shopping_result.get("places", []):
                name = str(place.get("name") or "未命名地点")[:240]
                address = place.get("address")
                location = place.get("location")
                place_key = hashlib.sha256(
                    f"{name}|{address or ''}|{location or ''}".encode()
                ).hexdigest()[:64]
                db.add(
                    MapPlace(
                        run_id=run.id,
                        owner_id=run.owner_id,
                        task_id=run.task_id,
                        task_revision_id=run.task_revision_id,
                        revision=run.revision,
                        place_key=place_key,
                        name=name,
                        address=str(address)[:240] if address else None,
                        location=str(location)[:240] if location else None,
                        phone=str(place.get("phone"))[:80] if place.get("phone") else None,
                        url=str(place.get("url"))[:240] if place.get("url") else None,
                        query=query,
                        city=city,
                        source_service=str(source.get("service_id", "map"))[:64],
                        source_tool=str(source.get("tool", ""))[:128],
                        observed_at=observed_at,
                    )
                )
        if shopping_artifacts is not None:
            candidates_by_product: dict[str, ShoppingCandidate] = {}
            for draft in shopping_artifacts.get("candidates", []):
                candidate = ShoppingCandidate(
                    run_id=run.id,
                    owner_id=run.owner_id,
                    task_id=run.task_id,
                    task_revision_id=run.task_revision_id,
                    revision=run.revision,
                    product_id=draft.product_id,
                    name=draft.name,
                    unit_price=draft.unit_price,
                    currency=draft.currency,
                    unit=draft.unit,
                    distributable_units=draft.distributable_units,
                    source_type=draft.source_type,
                    source_service=draft.source_service,
                    simulated=draft.simulated,
                    availability=draft.availability,
                    quoted_at=draft.quoted_at,
                    queried_at=draft.queried_at,
                )
                db.add(candidate)
                candidates_by_product[draft.product_id] = candidate
            plan_draft = shopping_artifacts.get("plan")
            if plan_draft is not None:
                candidate = candidates_by_product[plan_draft.candidate_product_id]
                db.flush()
                db.add(
                    ShoppingPlan(
                        run_id=run.id,
                        owner_id=run.owner_id,
                        task_id=run.task_id,
                        task_revision_id=run.task_revision_id,
                        revision=run.revision,
                        status="valid",
                        people=plan_draft.people,
                        covered_people=plan_draft.covered_people,
                        budget=plan_draft.budget,
                        total=plan_draft.total,
                        remaining=plan_draft.remaining,
                        currency=plan_draft.currency,
                        unknown_fees=plan_draft.unknown_fees,
                        note=plan_draft.note,
                        items=[
                            ShoppingPlanItem(
                                candidate_id=candidate.id,
                                package_quantity=plan_draft.package_quantity,
                                covered_people=plan_draft.covered_people,
                                subtotal=plan_draft.total,
                            )
                        ],
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
    shopping_artifacts: dict[str, object] | None = None,
    budget: dict[str, object] | None = None,
    decision: dict[str, object] | None = None,
) -> bool:
    return _finish_claim(
        db,
        claim,
        "completed",
        diagnostic=diagnostic,
        shopping_result=shopping_result,
        shopping_artifacts=shopping_artifacts,
        budget=budget,
        decision=decision,
    )


def fail_claim(
    db: Session,
    claim: RunClaim,
    error_summary: str,
    budget: dict[str, object] | None = None,
) -> bool:
    return _finish_claim(
        db, claim, "failed", error_summary=error_summary[:500], budget=budget
    )


def cancel_claim(
    db: Session, claim: RunClaim, budget: dict[str, object] | None = None
) -> bool:
    return _finish_claim(
        db,
        claim,
        "cancelled",
        diagnostic={"message": "run cancelled at worker checkpoint"},
        budget=budget,
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
    if run.execution_type not in {
        "shopping_research",
        "shopping_agent",
        "map_places",
        "capability_router",
        "direct_answer",
    }:
        raise RunNotFoundError
    result = db.scalar(
        select(ShoppingRunResult).where(ShoppingRunResult.run_id == run_id)
    )
    if result is None:
        raise RunNotFoundError
    return result


def get_map_places(
    db: Session, owner_id: uuid.UUID, run_id: uuid.UUID
) -> list[MapPlace]:
    _owned_run(db, owner_id, run_id)
    return list(
        db.scalars(
            select(MapPlace)
            .where(MapPlace.run_id == run_id, MapPlace.owner_id == owner_id)
            .order_by(MapPlace.name, MapPlace.id)
        )
    )


def get_shopping_artifacts(
    db: Session, owner_id: uuid.UUID, run_id: uuid.UUID
) -> tuple[list[ShoppingCandidate], ShoppingPlan | None]:
    _owned_run(db, owner_id, run_id)
    candidates = list(
        db.scalars(
            select(ShoppingCandidate)
            .where(
                ShoppingCandidate.run_id == run_id,
                ShoppingCandidate.owner_id == owner_id,
            )
            .order_by(ShoppingCandidate.unit_price, ShoppingCandidate.product_id)
        )
    )
    plan = db.scalar(
        select(ShoppingPlan)
        .where(ShoppingPlan.run_id == run_id, ShoppingPlan.owner_id == owner_id)
        .options(
            selectinload(ShoppingPlan.items).selectinload(ShoppingPlanItem.candidate)
        )
    )
    return candidates, plan