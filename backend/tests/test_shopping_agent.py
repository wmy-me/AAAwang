"""Focused checks for the 012 supervisor/discovery LangGraph."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

from mcp.types import CallToolResult, TextContent, Tool
from pydantic import SecretStr

from life_agent.agents.shopping import run_shopping_agent
from life_agent.core.config import Settings
from life_agent.core.llm import LLMRequestError
from life_agent.core.llm.tool_loop import _model_tool_name
from life_agent.tools.mcp import DiscoveredTool, McpCallResult


class FakeCompletions:
    def __init__(self, messages: list[SimpleNamespace]) -> None:
        self.messages = iter(messages)
        self.requests: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self.requests.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=next(self.messages))])


class FakeModel:
    def __init__(self, messages: list[SimpleNamespace]) -> None:
        completions = FakeCompletions(messages)
        self.completions = completions
        self.chat = SimpleNamespace(completions=completions)


class FakeConnection:
    protocol_version = "2025-11-25"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def list_tools(self) -> list[DiscoveredTool]:
        schema = {
            "type": "object",
            "properties": {"keyword": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["keyword"],
            "additionalProperties": False,
        }
        return [
            DiscoveredTool(
                "shopping",
                "search_products",
                Tool(name="search_products", description="search", inputSchema=schema),
            )
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> McpCallResult:
        self.calls.append((name, arguments))
        return McpCallResult(
            "shopping",
            name,
            CallToolResult(
                content=[TextContent(type="text", text="mock")],
                structuredContent={
                    "products": [{"name": "彩色铅笔套装", "unit_price": 12.8}],
                    "source_type": "mock",
                },
                isError=False,
            ),
        )


class FakeMcp:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    @asynccontextmanager
    async def connect(self, _service_id: str) -> AsyncIterator[FakeConnection]:
        yield self.connection


def message(content: str | None = None, *, tool: str | None = None, arguments: str = "{}") -> SimpleNamespace:
    calls = None
    if tool is not None:
        calls = [SimpleNamespace(id="delegate-1", function=SimpleNamespace(name=tool, arguments=arguments))]
    return SimpleNamespace(content=content, tool_calls=calls)


def messages(*calls: tuple[str, str]) -> SimpleNamespace:
    return SimpleNamespace(
        content=None,
        tool_calls=[
            SimpleNamespace(
                id=f"delegate-{index}",
                function=SimpleNamespace(name=name, arguments=arguments),
            )
            for index, (name, arguments) in enumerate(calls, start=1)
        ],
    )


def settings() -> Settings:
    return Settings(llm_api_key=SecretStr("test-key"))


def test_direct_answer_does_not_delegate_or_call_mcp() -> None:
    supervisor = FakeModel([message(json.dumps({"decision_type": "direct_answer", "answer": "可以直接回答。"}))])
    connection = FakeConnection()
    result = asyncio.run(
        run_shopping_agent(settings(), "什么是预算", {}, model_client=supervisor, mcp_client=FakeMcp(connection))
    )
    assert result.decision_type == "direct_answer"
    assert result.delegated is False
    assert result.mcp_call_count == 0
    assert connection.calls == []


def test_clarification_does_not_delegate_or_call_mcp() -> None:
    supervisor = FakeModel([message(json.dumps({"decision_type": "clarification", "answer": "请补充要买什么。"}))])
    connection = FakeConnection()
    result = asyncio.run(
        run_shopping_agent(settings(), "帮我买东西", {}, model_client=supervisor, mcp_client=FakeMcp(connection))
    )
    assert result.decision_type == "clarification"
    assert result.mcp_call_count == 0
    assert connection.calls == []


def test_fenced_json_decision_is_accepted_without_retry() -> None:
    content = '```json\n{"decision_type":"direct_answer","answer":"可以直接回答。"}\n```'
    supervisor = FakeModel([message(content)])
    result = asyncio.run(
        run_shopping_agent(settings(), "什么是预算", {}, model_client=supervisor)
    )
    assert result.decision_type == "direct_answer"
    assert len(supervisor.completions.requests) == 1
    assert result.source["model_requests"] == 1


def test_json_with_trailing_noise_is_accepted_without_retry() -> None:
    content = '{"decision_type":"clarification","answer":"请补充预算。"}"}'
    supervisor = FakeModel([message(content)])
    result = asyncio.run(
        run_shopping_agent(settings(), "买奖品", {}, model_client=supervisor)
    )
    assert result.decision_type == "clarification"
    assert result.answer == "请补充预算。"
    assert len(supervisor.completions.requests) == 1


def test_plain_text_is_corrected_with_one_bounded_retry() -> None:
    supervisor = FakeModel(
        [
            message("我需要先确认预算和人数。"),
            message(json.dumps({"decision_type": "clarification", "answer": "请补充预算和人数。"})),
        ]
    )
    result = asyncio.run(
        run_shopping_agent(settings(), "买奖品", {}, model_client=supervisor)
    )
    assert result.decision_type == "clarification"
    assert result.delegated is False
    assert len(supervisor.completions.requests) == 2
    assert result.source["model_requests"] == 2


def test_multiple_delegations_are_corrected_before_any_mcp_call() -> None:
    supervisor = FakeModel(
        [
            messages(
                ("delegate_shopping_discovery", json.dumps({"keyword": "铅笔"})),
                ("delegate_shopping_discovery", json.dumps({"keyword": "文具"})),
            ),
            message(
                tool="delegate_shopping_discovery",
                arguments=json.dumps({"keyword": "铅笔", "limit": 2}),
            ),
            message("已根据模拟商品查询结果整理回复。"),
        ]
    )
    discovery = FakeModel(
        [
            message(
                tool=_model_tool_name("shopping:search_products"),
                arguments=json.dumps({"keyword": "铅笔", "limit": 2}),
            ),
            message("模拟候选：铅笔套装。"),
        ]
    )
    connection = FakeConnection()
    result = asyncio.run(
        run_shopping_agent(
            settings(),
            "给学生买铅笔奖品",
            {"budget": 20},
            model_client=supervisor,
            discovery_model_client=discovery,
            mcp_client=FakeMcp(connection),
        )
    )
    assert result.decision_type == "delegated_discovery"
    assert len(supervisor.completions.requests) == 3
    assert result.source["model_requests"] == 5
    assert result.mcp_call_count == 1
    assert connection.calls == [("search_products", {"keyword": "铅笔", "limit": 2})]
    correction = supervisor.completions.requests[1]["messages"][-1]["content"]
    assert "任何委派都没有执行" in correction
    rejected = [
        item
        for item in supervisor.completions.requests[1]["messages"]
        if item["role"] == "assistant"
    ][-1]
    assert "tool_calls" not in rejected
    assert len(supervisor.completions.requests[0]["messages"][0]["content"]) > 0


def test_invalid_delegation_is_corrected_once_and_still_cannot_call_unknown_tool() -> None:
    supervisor = FakeModel(
        [
            message(tool="unknown_delegate", arguments=json.dumps({"keyword": "铅笔"})),
            message(json.dumps({"decision_type": "clarification", "answer": "请补充预算。"})),
        ]
    )
    connection = FakeConnection()
    result = asyncio.run(
        run_shopping_agent(
            settings(), "买铅笔", {}, model_client=supervisor, mcp_client=FakeMcp(connection)
        )
    )
    assert result.decision_type == "clarification"
    assert result.mcp_call_count == 0
    assert connection.calls == []
    assert len(supervisor.completions.requests) == 2


def test_invalid_decision_correction_respects_shared_model_budget() -> None:
    from life_agent.core.budget import BudgetExceededError, BudgetLimits, RunBudget

    supervisor = FakeModel(
        [message(tool="unknown_delegate", arguments="{}"), message("不会执行")]
    )
    budget = RunBudget(limits=BudgetLimits(model_requests=1))
    try:
        asyncio.run(
            run_shopping_agent(
                settings(), "买铅笔", {}, model_client=supervisor, budget=budget
            )
        )
    except BudgetExceededError as exc:
        assert "model_budget_exhausted" in str(exc)
    else:
        raise AssertionError("expected shared model budget exhaustion")
    assert len(supervisor.completions.requests) == 1


def test_two_unstructured_replies_fail_safely_without_touching_mcp() -> None:
    supervisor = FakeModel([message("纯文本一"), message("纯文本二")])
    connection = FakeConnection()
    try:
        asyncio.run(
            run_shopping_agent(
                settings(), "买奖品", {}, model_client=supervisor, mcp_client=FakeMcp(connection)
            )
        )
    except LLMRequestError as exc:
        assert "决策" in str(exc)
    else:
        raise AssertionError("expected LLMRequestError")
    assert connection.calls == []


def test_delegation_uses_only_discovery_tool_and_persists_source_facts() -> None:
    supervisor = FakeModel(
        [
            message(
                tool="delegate_shopping_discovery",
                arguments=json.dumps({"keyword": "彩色铅笔", "limit": 2}),
            ),
            message("已根据模拟商品查询结果整理回复。"),
        ]
    )
    discovery = FakeModel(
        [
            message(tool=_model_tool_name("shopping:search_products"), arguments=json.dumps({"keyword": "彩色铅笔", "limit": 2})),
            message("模拟候选：彩色铅笔套装，12.8 元。"),
        ]
    )
    connection = FakeConnection()
    result = asyncio.run(
        run_shopping_agent(
            settings(),
            "给学生买一盒彩色铅笔作为奖品",
            {"budget": 15},
            model_client=supervisor,
            discovery_model_client=discovery,
            mcp_client=FakeMcp(connection),
        )
    )
    assert result.decision_type == "delegated_discovery"
    assert result.delegated is True
    assert result.mcp_call_count == 1
    assert connection.calls == [("search_products", {"keyword": "彩色铅笔", "limit": 2})]
    assert result.source["simulated"] is True
    assert result.source["tool"] == "shopping:search_products"
    assert "shopping_guidance" in supervisor.completions.requests[0]["messages"][0]["content"]
    assert "teacher_rewards" not in supervisor.completions.requests[0]["messages"][0]["content"]


def test_forced_discovery_skips_supervisor_and_requires_tool_call() -> None:
    supervisor = FakeModel([message("已根据模拟商品查询结果整理回复。")])
    discovery = FakeModel(
        [
            message(
                tool=_model_tool_name("shopping:search_products"),
                arguments=json.dumps({"keyword": "彩色铅笔", "limit": 2}),
            ),
            message("模拟候选：彩色铅笔套装，12.8 元。"),
        ]
    )
    connection = FakeConnection()
    result = asyncio.run(
        run_shopping_agent(
            settings(),
            "彩色铅笔",
            {"budget": 15},
            model_client=supervisor,
            discovery_model_client=discovery,
            mcp_client=FakeMcp(connection),
            force_discovery=True,
        )
    )

    assert result.decision_type == "delegated_discovery"
    assert result.delegated is True
    assert result.mcp_call_count == 1
    assert connection.calls == [
        ("search_products", {"keyword": "彩色铅笔", "limit": 2})
    ]
    assert discovery.completions.requests[0]["tool_choice"] == "required"
    assert len(supervisor.completions.requests) == 1
    assert result.source["model_requests"] == 3
