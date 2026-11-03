"""Owner-scoped immutable manual shopping-plan adjustments."""

import hashlib
import json
import uuid
from datetime import UTC
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from life_agent.db.models import (
    Conversation,
    Run,
    ShoppingCandidate,
    ShoppingPlanAdjustment,
    ShoppingPlanAdjustmentItem,
    Task,
)
from life_agent.modules.runs.service import RunNotFoundError
from life_agent.modules.shopping_plans.service import (
    CandidateDraft,
    PlanDraft,
    build_manual_plan_draft,
)


class AdjustmentConflictError(ValueError):
    """Raised when the current task adjustment version has changed."""

    def __init__(self, current_version: int) -> None:
        self.current_version = current_version
        super().__init__("shopping plan adjustment version conflict")


class AdjustmentIdempotencyConflictError(ValueError):
    """Raised when a client request ID is reused with different content."""


def _owned_task(db: Session, owner_id: uuid.UUID, task_id: uuid.UUID) -> Task:
    task = db.scalar(
        select(Task)
        .join(Conversation)
        .where(Task.id == task_id, Conversation.owner_id == owner_id)
        .with_for_update()
    )
    if task is None:
        raise RunNotFoundError
    return task


def _fingerprint(
    base_run_id: uuid.UUID,
    expected_revision: int,
    expected_adjustment_version: int,
    items: list[tuple[uuid.UUID, int]],
) -> str:
    payload = {
        "base_run_id": str(base_run_id),
        "expected_revision": expected_revision,
        "expected_adjustment_version": expected_adjustment_version,
        "items": sorted((str(candidate_id), quantity) for candidate_id, quantity in items),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()


def _candidate_draft(candidate: ShoppingCandidate) -> CandidateDraft:
    quoted_at = candidate.quoted_at
    if quoted_at is not None and quoted_at.tzinfo is None:
        quoted_at = quoted_at.replace(tzinfo=UTC)
    return CandidateDraft(
        product_id=candidate.product_id,
        name=candidate.name,
        unit_price=Decimal(str(candidate.unit_price)),
        currency=candidate.currency,
        unit=candidate.unit,
        distributable_units=candidate.distributable_units,
        source_type=candidate.source_type,
        source_service=candidate.source_service,
        simulated=candidate.simulated,
        availability=candidate.availability,
        quoted_at=quoted_at,
        queried_at=candidate.queried_at,
    )


def _current_version(db: Session, task_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.max(ShoppingPlanAdjustment.version), 0)).where(
                ShoppingPlanAdjustment.task_id == task_id
            )
        )
        or 0
    )


def create_adjustment(
    db: Session,
    owner_id: uuid.UUID,
    task_id: uuid.UUID,
    *,
    base_run_id: uuid.UUID,
    expected_revision: int,
    expected_adjustment_version: int,
    client_request_id: str,
    items: list[tuple[uuid.UUID, int]],
) -> ShoppingPlanAdjustment:
    task = _owned_task(db, owner_id, task_id)
    fingerprint = _fingerprint(
        base_run_id,
        expected_revision,
        expected_adjustment_version,
        items,
    )
    existing = db.scalar(
        select(ShoppingPlanAdjustment).where(
            ShoppingPlanAdjustment.task_id == task_id,
            ShoppingPlanAdjustment.client_request_id == client_request_id,
        )
    )
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise AdjustmentIdempotencyConflictError
        return existing
    if task.current_revision != expected_revision:
        raise AdjustmentConflictError(_current_version(db, task_id))
    current_version = _current_version(db, task_id)
    if current_version != expected_adjustment_version:
        raise AdjustmentConflictError(current_version)
    if not items or len({candidate_id for candidate_id, _ in items}) != len(items):
        raise ValueError("候选不能重复，且至少选择一项。")
    if any(quantity < 1 for _, quantity in items):
        raise ValueError("包装数量必须是正整数。")

    base_run = db.scalar(
        select(Run).where(
            Run.id == base_run_id,
            Run.owner_id == owner_id,
            Run.task_id == task_id,
            Run.revision == expected_revision,
        )
    )
    if base_run is None or base_run.status != "completed":
        raise RunNotFoundError
    candidates = list(
        db.scalars(
            select(ShoppingCandidate).where(
                ShoppingCandidate.run_id == base_run_id,
                ShoppingCandidate.owner_id == owner_id,
                ShoppingCandidate.task_id == task_id,
                ShoppingCandidate.revision == expected_revision,
            )
        )
    )
    candidate_by_id = {candidate.id: candidate for candidate in candidates}
    if any(candidate_id not in candidate_by_id for candidate_id, _ in items):
        raise RunNotFoundError
    drafts = [_candidate_draft(candidate) for candidate in candidates]
    product_ids = [(candidate_by_id[candidate_id].product_id, quantity) for candidate_id, quantity in items]
    plan: PlanDraft | None = build_manual_plan_draft(drafts, dict(base_run.conditions), product_ids)
    if plan is None:
        raise ValueError("所选候选无法满足当前人数、预算、币种或可用性条件。")

    for adjustment in db.scalars(
        select(ShoppingPlanAdjustment).where(
            ShoppingPlanAdjustment.task_id == task_id,
            ShoppingPlanAdjustment.is_current.is_(True),
        )
    ):
        adjustment.is_current = False
    adjustment = ShoppingPlanAdjustment(
        owner_id=owner_id,
        task_id=task_id,
        task_revision_id=base_run.task_revision_id,
        base_run_id=base_run_id,
        version=current_version + 1,
        client_request_id=client_request_id,
        request_fingerprint=fingerprint,
        source="manual_adjustment",
        status="valid",
        is_current=True,
        people=plan.people,
        covered_people=plan.covered_people,
        budget=plan.budget,
        total=plan.total,
        remaining=plan.remaining,
        currency=plan.currency,
        unknown_fees=plan.unknown_fees,
        note=plan.note,
    )
    db.add(adjustment)
    db.flush()
    for item in plan.items:
        candidate = next(
            candidate
            for candidate in candidates
            if candidate.product_id == item.candidate_product_id
        )
        db.add(
            ShoppingPlanAdjustmentItem(
                adjustment_id=adjustment.id,
                candidate_id=candidate.id,
                package_quantity=item.package_quantity,
                covered_people=item.covered_people,
                subtotal=item.subtotal,
            )
        )
    db.commit()
    return get_adjustment(db, owner_id, task_id, adjustment.id)


def get_adjustment(
    db: Session, owner_id: uuid.UUID, task_id: uuid.UUID, adjustment_id: uuid.UUID
) -> ShoppingPlanAdjustment:
    adjustment = db.scalar(
        select(ShoppingPlanAdjustment)
        .where(
            ShoppingPlanAdjustment.id == adjustment_id,
            ShoppingPlanAdjustment.owner_id == owner_id,
            ShoppingPlanAdjustment.task_id == task_id,
        )
        .options(
            selectinload(ShoppingPlanAdjustment.items).selectinload(
                ShoppingPlanAdjustmentItem.candidate
            )
        )
    )
    if adjustment is None:
        raise RunNotFoundError
    return adjustment


def list_adjustments(
    db: Session, owner_id: uuid.UUID, task_id: uuid.UUID
) -> list[ShoppingPlanAdjustment]:
    _owned_task(db, owner_id, task_id)
    return list(
        db.scalars(
            select(ShoppingPlanAdjustment)
            .where(
                ShoppingPlanAdjustment.owner_id == owner_id,
                ShoppingPlanAdjustment.task_id == task_id,
            )
            .options(
                selectinload(ShoppingPlanAdjustment.items).selectinload(
                    ShoppingPlanAdjustmentItem.candidate
                )
            )
            .order_by(ShoppingPlanAdjustment.version.desc())
        )
    )
