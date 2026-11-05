import asyncio
from decimal import Decimal

from life_agent.agents.coordinator.service import decide_capabilities
from life_agent.agents.discovery import service as discovery_service
from life_agent.agents.procurement.service import build_validated_plan


def test_coordinator_entrypoint_keeps_worker_implementation_behind_boundary(monkeypatch) -> None:
    expected = {"kind": "direct", "capability_ids": []}

    def fake_decision(settings, claim, budget):
        return expected

    monkeypatch.setattr(
        "life_agent.worker.runner._run_capability_decision_impl", fake_decision
    )
    assert decide_capabilities(object(), object(), object()) is expected


def test_discovery_entrypoint_delegates_without_creating_a_second_graph(monkeypatch) -> None:
    expected = object()

    async def fake_discovery(*args, **kwargs):
        return expected

    monkeypatch.setattr(discovery_service, "run_shopping_agent", fake_discovery)
    result = asyncio.run(
        discovery_service.run_product_discovery(object(), "买文具", {})
    )
    assert result is expected


def test_procurement_entrypoint_keeps_plan_calculation_deterministic() -> None:
    source = {
        "service_id": "shopping",
        "simulated": True,
        "tool_result": {
            "source_type": "mock",
            "products": [
                {
                    "product_id": "pencil-1",
                    "name": "彩色铅笔",
                    "unit_price": "12.80",
                    "currency": "CNY",
                    "unit": "套",
                    "distributable_units": 25,
                    "availability": "有货",
                }
            ],
        },
    }
    artifacts, answer = build_validated_plan(source, {"people": 25, "budget": 200})
    assert artifacts["plan"].total == Decimal("12.80")
    assert answer is not None
    assert "服务端校验方案" in answer
