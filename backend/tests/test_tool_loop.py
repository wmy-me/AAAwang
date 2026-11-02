"""Focused checks for the bounded model-to-MCP tool loop."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast

import pytest
from mcp.types import CallToolResult, TextContent, Tool
from openai import AsyncOpenAI
from pydantic import SecretStr

from life_agent.core.config import Settings
from life_agent.core.llm import ToolLoopError, run_tool_loop
from life_agent.tools.mcp import DiscoveredTool, McpCallResult


class FakeCompletions:
    def __init__(self, messages: list[SimpleNamespace]) -> None:
        self._messages = iter(messages)
        self.requests: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self.requests.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=next(self._messages))])


class FakeModelClient:
    def __init__(self, messages: list[SimpleNamespace]) -> None:
        self.completions = FakeCompletions(messages)
        self.chat = SimpleNamespace(completions=self.completions)


class FakeConnection:
    protocol_version = "2025-11-25"

    def __init__(self, service_id: str = "shopping", *, empty: bool = False) -> None:
        self.service_id = service_id
        self.empty = empty
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def list_tools(self) -> list[DiscoveredTool]:
        schema = {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "minLength": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": ["keyword"],
            "additionalProperties": False,
        }
        return [
            DiscoveredTool(
                self.service_id,
                "search_products",
                Tool(name="search_products", description="search", inputSchema=schema),
            ),
            DiscoveredTool(
                self.service_id,
                "write_order",
                Tool(name="write_order", description="write", inputSchema=schema),
            ),
        ]

    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> McpCallResult:
        self.calls.append((tool_name, arguments))
        result = CallToolResult(
            content=[TextContent(type="text", text="mock")],
            structuredContent={
                "products": (
                    []
                    if self.empty
                    else [{"name": "彩色铅笔套装", "unit_price": 12.8}]
                ),
                "source_type": "mock",
                "source_service": "shopping-mcp",
            },
            isError=False,
        )
        return McpCallResult(self.service_id, tool_name, result)


class FakeMcpClient:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    @asynccontextmanager
    async def connect(self, _service_id: str) -> AsyncIterator[FakeConnection]:
        yield self.connection


def model_message(
    content: str | None = None,
    *,
    tool_name: str | None = None,
    arguments: str = "{}",
) -> SimpleNamespace:
    calls = None
    if tool_name is not None:
        calls = [
            SimpleNamespace(
                id="call-1",
                function=SimpleNamespace(name=tool_name, arguments=arguments),
            )
        ]
    return SimpleNamespace(content=content, tool_calls=calls)


def settings() -> Settings:
    return Settings(llm_api_key=SecretStr("test-key"))


def test_single_allowed_tool_call_is_validated_routed_and_linked() -> None:
    connection = FakeConnection()
    first_client = FakeModelClient([model_message("choose")])

    async def discover_model_name() -> str:
        result = await run_tool_loop(
            settings(),
            "直接回答",
            service_id="shopping",
            allowed_tool_names={"search_products"},
            model_client=cast(AsyncOpenAI, first_client),
            mcp_client=cast(Any, FakeMcpClient(connection)),
        )
        assert result.model_called_tool is False
        return first_client.completions.requests[0]["tools"][0]["function"]["name"]

    model_name = asyncio.run(discover_model_name())
    connection = FakeConnection()
    client = FakeModelClient(
        [
            model_message(
                tool_name=model_name,
                arguments=json.dumps({"keyword": "彩色铅笔", "limit": 2}),
            ),
            model_message("彩色铅笔套装的模拟价格是 12.8 元。"),
        ]
    )

    result = asyncio.run(
        run_tool_loop(
            settings(),
            "请查询",
            service_id="shopping",
            allowed_tool_names={"search_products"},
            model_client=cast(AsyncOpenAI, client),
            mcp_client=cast(Any, FakeMcpClient(connection)),
        )
    )

    assert connection.calls == [("search_products", {"keyword": "彩色铅笔", "limit": 2})]
    assert result.called_tool == "shopping:search_products"
    assert result.model_requests == 2
    second_messages = client.completions.requests[1]["messages"]
    assert second_messages[-1]["tool_call_id"] == "call-1"
    assert json.loads(second_messages[-1]["content"])["source_type"] == "mock"
    exposed_names = [
        tool["function"]["name"]
        for tool in client.completions.requests[0]["tools"]
    ]
    assert len(exposed_names) == 1


@pytest.mark.parametrize(
    ("message", "error"),
    [
        (model_message(tool_name="unknown", arguments="{}"), "未知或未授权"),
        (model_message(tool_name="placeholder", arguments="not-json"), "有效 JSON"),
        (
            model_message(tool_name="placeholder", arguments='{"keyword":"x","limit":99}'),
            "不符合 MCP 输入 schema",
        ),
    ],
)
def test_invalid_or_unauthorized_calls_do_not_execute(
    message: SimpleNamespace, error: str
) -> None:
    connection = FakeConnection()
    probe = FakeModelClient([model_message("probe")])
    asyncio.run(
        run_tool_loop(
            settings(),
            "probe",
            service_id="shopping",
            allowed_tool_names={"search_products"},
            model_client=cast(AsyncOpenAI, probe),
            mcp_client=cast(Any, FakeMcpClient(connection)),
        )
    )
    model_name = probe.completions.requests[0]["tools"][0]["function"]["name"]
    if message.tool_calls and message.tool_calls[0].function.name == "placeholder":
        message.tool_calls[0].function.name = model_name
    client = FakeModelClient([message])

    with pytest.raises(ToolLoopError, match=error):
        asyncio.run(
            run_tool_loop(
                settings(),
                "test",
                service_id="shopping",
                allowed_tool_names={"search_products"},
                model_client=cast(AsyncOpenAI, client),
                mcp_client=cast(Any, FakeMcpClient(connection)),
            )
        )

    assert connection.calls == []


def test_direct_answer_does_not_call_mcp_tool() -> None:
    connection = FakeConnection()
    client = FakeModelClient([model_message("无需查询。")])

    result = asyncio.run(
        run_tool_loop(
            settings(),
            "你好",
            service_id="shopping",
            allowed_tool_names={"search_products"},
            model_client=cast(AsyncOpenAI, client),
            mcp_client=cast(Any, FakeMcpClient(connection)),
        )
    )

    assert result.model_called_tool is False
    assert connection.calls == []


def test_multiple_tool_calls_are_rejected_before_execution() -> None:
    connection = FakeConnection()
    probe = FakeModelClient([model_message("probe")])
    asyncio.run(
        run_tool_loop(
            settings(),
            "probe",
            service_id="shopping",
            allowed_tool_names={"search_products"},
            model_client=cast(AsyncOpenAI, probe),
            mcp_client=cast(Any, FakeMcpClient(connection)),
        )
    )
    model_name = probe.completions.requests[0]["tools"][0]["function"]["name"]
    message = model_message(tool_name=model_name, arguments='{"keyword":"笔"}')
    message.tool_calls.append(message.tool_calls[0])
    client = FakeModelClient([message])

    with pytest.raises(ToolLoopError, match="多个工具调用"):
        asyncio.run(
            run_tool_loop(
                settings(),
                "test",
                service_id="shopping",
                allowed_tool_names={"search_products"},
                model_client=cast(AsyncOpenAI, client),
                mcp_client=cast(Any, FakeMcpClient(connection)),
            )
        )

    assert connection.calls == []


def test_empty_result_is_returned_to_model_as_success() -> None:
    connection = FakeConnection(empty=True)
    probe = FakeModelClient([model_message("probe")])
    asyncio.run(
        run_tool_loop(
            settings(),
            "probe",
            service_id="shopping",
            allowed_tool_names={"search_products"},
            model_client=cast(AsyncOpenAI, probe),
            mcp_client=cast(Any, FakeMcpClient(connection)),
        )
    )
    model_name = probe.completions.requests[0]["tools"][0]["function"]["name"]
    client = FakeModelClient(
        [
            model_message(tool_name=model_name, arguments='{"keyword":"不存在"}'),
            model_message("没有找到匹配的模拟商品。"),
        ]
    )

    result = asyncio.run(
        run_tool_loop(
            settings(),
            "查询不存在的商品",
            service_id="shopping",
            allowed_tool_names={"search_products"},
            model_client=cast(AsyncOpenAI, client),
            mcp_client=cast(Any, FakeMcpClient(connection)),
        )
    )

    assert result.tool_result["products"] == []
    assert result.answer == "没有找到匹配的模拟商品。"


def test_same_raw_tool_name_has_distinct_model_names_per_service() -> None:
    names = []
    for service_id in ("shopping", "alternate"):
        connection = FakeConnection(service_id)
        client = FakeModelClient([model_message("direct")])
        asyncio.run(
            run_tool_loop(
                settings(),
                "test",
                service_id=service_id,
                allowed_tool_names={"search_products"},
                model_client=cast(AsyncOpenAI, client),
                mcp_client=cast(Any, FakeMcpClient(connection)),
            )
        )
        names.append(client.completions.requests[0]["tools"][0]["function"]["name"])

    assert names[0] != names[1]


def test_repeated_tool_call_in_final_response_is_rejected() -> None:
    connection = FakeConnection()
    probe = FakeModelClient([model_message("probe")])
    asyncio.run(
        run_tool_loop(
            settings(),
            "probe",
            service_id="shopping",
            allowed_tool_names={"search_products"},
            model_client=cast(AsyncOpenAI, probe),
            mcp_client=cast(Any, FakeMcpClient(connection)),
        )
    )
    model_name = probe.completions.requests[0]["tools"][0]["function"]["name"]
    client = FakeModelClient(
        [
            model_message(tool_name=model_name, arguments='{"keyword":"笔"}'),
            model_message(tool_name=model_name, arguments='{"keyword":"本"}'),
        ]
    )

    with pytest.raises(ToolLoopError, match="最终回复中再次请求工具"):
        asyncio.run(
            run_tool_loop(
                settings(),
                "test",
                service_id="shopping",
                allowed_tool_names={"search_products"},
                model_client=cast(AsyncOpenAI, client),
                mcp_client=cast(Any, FakeMcpClient(connection)),
            )
        )

    assert len(connection.calls) == 1