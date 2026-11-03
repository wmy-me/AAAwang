"""Deterministic candidate normalization and shopping-plan validation."""

from datetime import UTC, datetime
from decimal import Decimal

from life_agent.modules.shopping_plans.service import (
    build_artifacts,
    build_candidate_drafts,
    build_plan_draft,
    validated_plan_answer,
)


def source(products: list[dict[str, object]]) -> dict[str, object]:
    return {
        "simulated": True,
        "service_id": "shopping",
        "tool_result": {
            "products": products,
            "source_type": "mock",
            "source_service": "shopping-mcp",
        },
    }


def product(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "product_id": "mock-prize-stationery",
        "name": "学生奖品文具套装",
        "unit_price": "6.50",
        "currency": "CNY",
        "unit": "1套/包",
        "distributable_units": 1,
        "availability": "模拟有货",
        "quoted_at": "2026-11-03T00:00:00Z",
    }
    value.update(overrides)
    return value


def test_plan_covers_25_people_and_recalculates_money() -> None:
    candidates = build_candidate_drafts(source([product()]), datetime.now(UTC))
    plan = build_plan_draft(candidates, {"people": 25, "budget": 200})

    assert len(candidates) == 1
    assert plan is not None
    assert plan.package_quantity == 25
    assert plan.covered_people == 25
    assert plan.total == Decimal("162.50")
    assert plan.remaining == Decimal("37.50")
    assert plan.unknown_fees is True


def test_package_share_count_uses_ceiling() -> None:
    candidates = build_candidate_drafts(
        source([product(product_id="stickers", unit_price="6.90", distributable_units=12)]),
        datetime.now(UTC),
    )
    plan = build_plan_draft(candidates, {"people": 25, "budget": 200})

    assert plan is not None
    assert plan.package_quantity == 3
    assert plan.covered_people == 36
    assert plan.total == Decimal("20.70")


def test_invalid_or_duplicate_candidate_is_not_snapshotted() -> None:
    candidates = build_candidate_drafts(
        source([product(), product(name="重复"), product(product_id="fabricated", unit_price="unknown")]),
        datetime.now(UTC),
    )

    assert [candidate.product_id for candidate in candidates] == ["mock-prize-stationery"]


def test_budget_shortfall_or_missing_people_has_no_valid_plan() -> None:
    candidates = build_candidate_drafts(source([product()]), datetime.now(UTC))

    assert build_plan_draft(candidates, {"people": 25, "budget": 100}) is None
    assert build_plan_draft(candidates, {"budget": 200}) is None


def test_validated_answer_uses_server_quantity_and_money() -> None:
    artifacts = build_artifacts(
        source(
            [
                product(
                    product_id="stickers",
                    name="奖励贴纸包",
                    unit_price="6.90",
                    distributable_units=25,
                )
            ]
        ),
        {"people": 25, "budget": 180},
    )

    answer = validated_plan_answer(artifacts)

    assert answer is not None
    assert "奖励贴纸包 × 1 包" in answer
    assert "商品小计 ¥6.90" in answer
    assert "预算 ¥180.00" in answer
    assert "余量 ¥173.10" in answer
