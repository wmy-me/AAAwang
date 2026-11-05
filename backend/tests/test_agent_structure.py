import asyncio
from decimal import Decimal
from types import SimpleNamespace

from life_agent.agents.coordinator import service as coordinator
from life_agent.agents.coordinator.service import decide_capabilities
from life_agent.agents.discovery import service as discovery_service
from life_agent.agents.procurement.service import build_validated_plan
from life_agent.core.llm.deepseek import LLMResult
from life_agent.worker import runner


def test_coordinator_owns_decision_prompt_and_parser(monkeypatch) -> None:
    assert not hasattr(runner, "_run_capability_decision_impl")
    captured: dict[str, str] = {}

    async def fake_call(_settings, prompt, **_kwargs):
        captured["prompt"] = prompt
        return LLMResult('{"kind":"direct","capability_ids":[],"reason":"问候"}')

    monkeypatch.setattr(coordinator, "call_deepseek", fake_call)
    monkeypatch.setattr(
        coordinator,
        "discover_capability_tools",
        lambda settings, _budget=None: (set(), {}),
    )
    decision = decide_capabilities(
        object(),
        SimpleNamespace(goal="给同学买毕业礼物", input_message="你好", conditions={}),
        runner.RunBudget(),
    )

    assert "任务目标：给同学买毕业礼物" in captured["prompt"]
    assert decision["kind"] == "direct"


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
