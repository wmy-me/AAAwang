"""Normalize MCP product evidence and deterministically validate a shopping plan."""

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

MONEY = Decimal("0.01")


@dataclass(frozen=True)
class CandidateDraft:
    product_id: str
    name: str
    unit_price: Decimal
    currency: str
    unit: str
    distributable_units: int
    source_type: str
    source_service: str
    simulated: bool
    availability: str
    quoted_at: datetime | None
    queried_at: datetime


@dataclass(frozen=True)
class PlanDraft:
    candidate_product_id: str
    package_quantity: int
    covered_people: int
    people: int
    budget: Decimal
    total: Decimal
    remaining: Decimal
    currency: str
    unknown_fees: bool
    note: str
    items: tuple["PlanItemDraft", ...] = ()


@dataclass(frozen=True)
class PlanItemDraft:
    candidate_product_id: str
    package_quantity: int
    covered_people: int
    subtotal: Decimal


def _money(value: object) -> Decimal:
    try:
        amount = Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("invalid unit price") from exc
    if amount < 0:
        raise ValueError("unit price must be non-negative")
    return amount


def _quoted_at(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("invalid quoted_at")
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def build_candidate_drafts(source: dict[str, object], queried_at: datetime) -> list[CandidateDraft]:
    tool_result = source.get("tool_result")
    if not isinstance(tool_result, dict):
        return []
    products = tool_result.get("products")
    if not isinstance(products, list):
        return []
    source_type = str(tool_result.get("source_type", "unknown"))[:32]
    source_service = str(tool_result.get("source_service", source.get("service_id", "unknown")))[:64]
    drafts: list[CandidateDraft] = []
    seen: set[str] = set()
    for raw in products:
        if not isinstance(raw, dict):
            continue
        try:
            product_id = str(raw["product_id"]).strip()
            name = str(raw["name"]).strip()
            currency = str(raw["currency"]).upper()
            unit = str(raw["unit"]).strip()
            distributable_units = int(raw["distributable_units"])
            availability = str(raw["availability"]).strip()
            if (
                not product_id
                or product_id in seen
                or not name
                or len(currency) != 3
                or not unit
                or distributable_units < 1
                or not availability
            ):
                continue
            draft = CandidateDraft(
                product_id=product_id[:128],
                name=name[:240],
                unit_price=_money(raw["unit_price"]),
                currency=currency,
                unit=unit[:120],
                distributable_units=distributable_units,
                source_type=source_type,
                source_service=source_service,
                simulated=source_type == "mock" or bool(source.get("simulated")),
                availability=availability[:120],
                quoted_at=_quoted_at(raw.get("quoted_at")),
                queried_at=queried_at,
            )
        except (KeyError, TypeError, ValueError):
            continue
        drafts.append(draft)
        seen.add(product_id)
    return drafts


def build_plan_draft(
    candidates: list[CandidateDraft], conditions: dict[str, object]
) -> PlanDraft | None:
    try:
        people = int(conditions["people"])
        budget = _money(conditions["budget"])
    except (KeyError, TypeError, ValueError):
        return None
    if people < 1 or budget <= 0:
        return None
    feasible: list[tuple[Decimal, CandidateDraft, int, int]] = []
    for candidate in candidates:
        if candidate.currency != "CNY" or "有货" not in candidate.availability:
            continue
        quantity = math.ceil(people / candidate.distributable_units)
        covered = quantity * candidate.distributable_units
        total = (candidate.unit_price * quantity).quantize(MONEY, rounding=ROUND_HALF_UP)
        if total <= budget:
            feasible.append((total, candidate, quantity, covered))
    if not feasible:
        return None
    total, candidate, quantity, covered = min(
        feasible, key=lambda item: (item[0], item[1].product_id)
    )
    item = PlanItemDraft(
        candidate_product_id=candidate.product_id,
        package_quantity=quantity,
        covered_people=covered,
        subtotal=total,
    )
    return PlanDraft(
        candidate_product_id=candidate.product_id,
        package_quantity=quantity,
        covered_people=covered,
        people=people,
        budget=budget,
        total=total,
        remaining=(budget - total).quantize(MONEY, rounding=ROUND_HALF_UP),
        currency="CNY",
        unknown_fees=True,
        note="商品金额已由服务端复算；运费、税费与优惠未知，未计入总额。",
        items=(item,),
    )


def build_manual_plan_draft(
    candidates: list[CandidateDraft],
    conditions: dict[str, object],
    selections: list[tuple[str, int]],
) -> PlanDraft | None:
    try:
        people = int(conditions["people"])
        budget = _money(conditions["budget"])
    except (KeyError, TypeError, ValueError):
        return None
    if people < 1 or budget <= 0 or not selections:
        return None
    by_id = {candidate.product_id: candidate for candidate in candidates}
    if len(by_id) != len(candidates) or len({product_id for product_id, _ in selections}) != len(selections):
        return None
    items: list[PlanItemDraft] = []
    total = Decimal("0.00")
    covered = 0
    for product_id, package_quantity in selections:
        candidate = by_id.get(product_id)
        if candidate is None or package_quantity < 1:
            return None
        if candidate.currency != "CNY" or "有货" not in candidate.availability:
            return None
        subtotal = (candidate.unit_price * package_quantity).quantize(
            MONEY, rounding=ROUND_HALF_UP
        )
        item_covered = candidate.distributable_units * package_quantity
        items.append(
            PlanItemDraft(
                candidate_product_id=product_id,
                package_quantity=package_quantity,
                covered_people=item_covered,
                subtotal=subtotal,
            )
        )
        total += subtotal
        covered += item_covered
    total = total.quantize(MONEY, rounding=ROUND_HALF_UP)
    if total > budget or covered < people:
        return None
    first = items[0]
    return PlanDraft(
        candidate_product_id=first.candidate_product_id,
        package_quantity=first.package_quantity,
        covered_people=covered,
        people=people,
        budget=budget,
        total=total,
        remaining=(budget - total).quantize(MONEY, rounding=ROUND_HALF_UP),
        currency="CNY",
        unknown_fees=True,
        note="商品金额已由服务端复算；运费、税费与优惠未知，未计入总额。",
        items=tuple(items),
    )


def build_artifacts(source: dict[str, object], conditions: dict[str, object]) -> dict[str, Any]:
    candidates = build_candidate_drafts(source, datetime.now(UTC))
    return {"candidates": candidates, "plan": build_plan_draft(candidates, conditions)}


def validated_plan_answer(artifacts: dict[str, Any]) -> str | None:
    plan = artifacts.get("plan")
    candidates = artifacts.get("candidates", [])
    if not isinstance(plan, PlanDraft) or not isinstance(candidates, list):
        return None
    candidate = next(
        (
            item
            for item in candidates
            if isinstance(item, CandidateDraft)
            and item.product_id == plan.candidate_product_id
        ),
        None,
    )
    if candidate is None:
        return None
    return (
        f"已生成服务端校验方案（模拟商品数据）：{candidate.name} × "
        f"{plan.package_quantity} 包，覆盖 {plan.covered_people}/{plan.people} 人；"
        f"商品小计 ¥{plan.total:.2f}，预算 ¥{plan.budget:.2f}，"
        f"余量 ¥{plan.remaining:.2f}。{plan.note}"
    )
