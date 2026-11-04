from types import SimpleNamespace

import pytest

from life_agent.core.llm import ToolLoopError
from life_agent.core.llm.deepseek import LLMResult
from life_agent.modules.runs.service import _map_source
from life_agent.worker import runner
from life_agent.worker.runner import _validate_claim_capabilities


def claim(execution_type: str, capability_ids: tuple[str, ...]):
    return SimpleNamespace(
        execution_type=execution_type,
        capability_ids=capability_ids,
    )


def test_worker_accepts_registered_matching_capability() -> None:
    _validate_claim_capabilities(
        claim("map_places", ("map_place_search",))
    )


def test_worker_rejects_cross_capability_execution() -> None:
    with pytest.raises(ToolLoopError, match="商品 Run 的能力快照无效"):
        _validate_claim_capabilities(
            claim("shopping_agent", ("map_place_search",))
        )


def test_worker_rejects_unknown_capability() -> None:
    with pytest.raises(ValueError, match="未注册能力"):
        _validate_claim_capabilities(claim("map_places", ("unknown",)))


def test_worker_accepts_combined_read_only_capabilities() -> None:
    _validate_claim_capabilities(
        claim(
            "capability_router",
            ("map_place_search", "shopping_product_discovery"),
        )
    )


def test_worker_rejects_unapproved_capability_combination() -> None:
    with pytest.raises(ValueError, match="未注册能力"):
        _validate_claim_capabilities(
            claim("capability_router", ("map_place_search", "unknown"))
        )


def test_combined_run_keeps_map_source_separate() -> None:
    source = _map_source(
        {
            "source": {"service_id": "shopping", "tool": "search_products"},
            "map_source": {"service_id": "map", "tool": "maps_text_search"},
        }
    )
    assert source == {"service_id": "map", "tool": "maps_text_search"}


def test_map_only_run_falls_back_to_its_source() -> None:
    source = _map_source(
        {"source": {"service_id": "map", "tool": "maps_text_search"}}
    )
    assert source == {"service_id": "map", "tool": "maps_text_search"}


def test_capability_decision_accepts_only_visible_registered_capabilities(monkeypatch) -> None:
    settings = SimpleNamespace(
        mcp_services={
            "shopping": SimpleNamespace(enabled=True),
            "map": SimpleNamespace(enabled=True),
        },
        map_mcp_tool_name="maps_text_search",
    )
    run_claim = SimpleNamespace(
        input_message="在上海找礼品店",
        goal="找礼品店",
        conditions={},
    )
    async def fake_call(*args, **kwargs):
        return LLMResult(
            '{"kind":"capabilities","capability_ids":["map_place_search"],"reason":"需要地点"}'
        )

    monkeypatch.setattr(runner, "call_deepseek", fake_call)
    monkeypatch.setattr(
        runner,
        "_discover_capability_tools",
        lambda settings, _budget=None: (
            {"map", "shopping"},
            {
                "map": {"maps_text_search": {"type": "object"}},
                "shopping": {"search_products": {"type": "object"}},
            },
        ),
    )

    decision = runner._run_capability_decision(settings, run_claim, runner.RunBudget())

    assert decision["capability_ids"] == ["map_place_search"]


def test_capability_decision_rejects_unregistered_capability(monkeypatch) -> None:
    settings = SimpleNamespace(
        mcp_services={"shopping": SimpleNamespace(enabled=True)},
        map_mcp_tool_name="maps_text_search",
    )
    run_claim = SimpleNamespace(input_message="买彩色铅笔", goal="购物", conditions={})
    async def fake_call(*args, **kwargs):
        return LLMResult('{"kind":"capabilities","capability_ids":["arbitrary_url_tool"]}')

    monkeypatch.setattr(runner, "call_deepseek", fake_call)
    monkeypatch.setattr(
        runner,
        "_discover_capability_tools",
        lambda settings, _budget=None: (
            {"shopping"},
            {"shopping": {"search_products": {"type": "object"}}},
        ),
    )

    with pytest.raises(ToolLoopError, match="不可见或重复"):
        runner._run_capability_decision(settings, run_claim, runner.RunBudget())


def test_capability_decision_treats_valid_ids_as_capabilities(monkeypatch) -> None:
    settings = SimpleNamespace(
        mcp_services={"shopping": SimpleNamespace(enabled=True)},
        map_mcp_tool_name="maps_text_search",
    )
    run_claim = SimpleNamespace(
        input_message="买彩色铅笔作为奖品", goal="购物", conditions={}
    )
    async def fake_call(*args, **kwargs):
        return LLMResult(
            '{"kind":"direct","capability_ids":["shopping_product_discovery"]}'
        )

    monkeypatch.setattr(runner, "call_deepseek", fake_call)
    monkeypatch.setattr(
        runner,
        "_discover_capability_tools",
        lambda settings, _budget=None: (
            {"shopping"},
            {"shopping": {"search_products": {"type": "object"}}},
        ),
    )

    decision = runner._run_capability_decision(settings, run_claim, runner.RunBudget())

    assert decision["kind"] == "capabilities"
    assert decision["capability_ids"] == ["shopping_product_discovery"]


def test_capability_decision_parses_fenced_json(monkeypatch) -> None:
    settings = SimpleNamespace(
        mcp_services={},
        map_mcp_tool_name="maps_text_search",
    )
    run_claim = SimpleNamespace(input_message="你好", goal="购物", conditions={})
    async def fake_call(*args, **kwargs):
        return LLMResult(
            '```json\n{"kind":"direct","capability_ids":[],"reason":"问候"}\n```'
        )

    monkeypatch.setattr(runner, "call_deepseek", fake_call)

    decision = runner._run_capability_decision(settings, run_claim, runner.RunBudget())

    assert decision["kind"] == "direct"


def test_capability_decision_downgrades_map_without_location(monkeypatch) -> None:
    settings = SimpleNamespace(
        mcp_services={"map": SimpleNamespace(enabled=True)},
        map_mcp_tool_name="maps_text_search",
    )
    run_claim = SimpleNamespace(input_message="找一家礼品店", goal="找店", conditions={})
    async def fake_call(*args, **kwargs):
        return LLMResult('{"kind":"capabilities","capability_ids":["map_place_search"]}')

    monkeypatch.setattr(runner, "call_deepseek", fake_call)
    monkeypatch.setattr(
        runner,
        "_discover_capability_tools",
        lambda settings, _budget=None: (
            {"map"},
            {"map": {"maps_text_search": {"type": "object"}}},
        ),
    )

    decision = runner._run_capability_decision(settings, run_claim, runner.RunBudget())

    assert decision["kind"] == "clarification"
    assert decision["capability_ids"] == []


def test_execution_rejects_changed_mcp_discovery(monkeypatch) -> None:
    claim_value = claim("map_places", ("map_place_search",))
    monkeypatch.setattr(
        runner,
        "_discover_capability_tools",
        lambda settings, _budget=None: ({"map"}, {"map": {"other_tool": {"type": "object"}}}),
    )

    with pytest.raises(ToolLoopError, match="工具发现结果已变化"):
        runner._validate_discovered_capabilities(SimpleNamespace(), claim_value)


def test_termination_reasons_are_bounded() -> None:
    assert runner._termination_reason(runner.BudgetExceededError("model_budget_exhausted")) == (
        "model_budget_exhausted"
    )
    assert runner._termination_reason(TimeoutError()) == "timeout"
    assert runner._termination_reason(ToolLoopError("执行租约丢失，结果不会提交。")) == (
        "lease_lost"
    )
    assert runner._termination_reason(
        ToolLoopError("购物Agent超过总执行时限，结果不会提交")
    ) == "timeout"
    assert runner._termination_reason(RuntimeError("boom")) == "failed"
