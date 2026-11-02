"""Focused checks for generic MCP service routing and result handling."""

import asyncio
from types import SimpleNamespace
from typing import Any, Self

import pytest
from mcp.types import CallToolResult, TextContent, Tool

import life_agent.tools.mcp.client as client_module
from life_agent.core.config import McpServiceConfig, Settings
from life_agent.tools.mcp import (
    McpClient,
    McpConnectionError,
    McpServiceConfigurationError,
    McpTimeoutError,
    McpToolExecutionError,
    McpToolNotFoundError,
)


class FakeSdkClient:
    def __init__(self, _url: str, **_kwargs: Any) -> None:
        self.protocol_version = "2025-11-25"
        self.server_info = SimpleNamespace(name="fake", version="1.0")
        self.error_result = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def list_tools(self) -> SimpleNamespace:
        return SimpleNamespace(
            tools=[Tool(name="echo", description="test", inputSchema={"type": "object"})]
        )

    async def call_tool(
        self, _name: str, _arguments: dict[str, Any]
    ) -> CallToolResult:
        return CallToolResult(
            content=[TextContent(type="text", text="ok")],
            structuredContent={"ok": True},
            isError=self.error_result,
        )


def make_settings() -> Settings:
    return Settings(
        mcp_services={
            "shopping": McpServiceConfig(url="http://127.0.0.1:8101/mcp"),
            "alternate": McpServiceConfig(url="http://127.0.0.1:9999/mcp"),
        }
    )


def test_two_service_ids_use_same_generic_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module, "Client", FakeSdkClient)

    async def exercise() -> list[str]:
        identities = []
        mcp_client = McpClient(make_settings())
        for service_id in ("shopping", "alternate"):
            async with mcp_client.connect(service_id) as connection:
                identities.append((await connection.list_tools())[0].qualified_name)
        return identities

    assert asyncio.run(exercise()) == ["shopping:echo", "alternate:echo"]


def test_unknown_service_is_rejected() -> None:
    with pytest.raises(McpServiceConfigurationError, match="未知 MCP 服务 ID"):
        asyncio.run(McpClient(make_settings()).connect("missing").__aenter__())


def test_unknown_tool_is_distinct(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module, "Client", FakeSdkClient)

    async def exercise() -> None:
        async with McpClient(make_settings()).connect("shopping") as connection:
            with pytest.raises(McpToolNotFoundError, match="未发现工具 missing"):
                await connection.call_tool("missing", {})

    asyncio.run(exercise())


def test_tool_error_preserves_sdk_result(monkeypatch: pytest.MonkeyPatch) -> None:
    class ErrorClient(FakeSdkClient):
        async def call_tool(
            self, name: str, arguments: dict[str, Any]
        ) -> CallToolResult:
            result = await super().call_tool(name, arguments)
            return result.model_copy(update={"is_error": True})

    monkeypatch.setattr(client_module, "Client", ErrorClient)

    async def exercise() -> None:
        async with McpClient(make_settings()).connect("shopping") as connection:
            with pytest.raises(McpToolExecutionError) as exc_info:
                await connection.call_tool("echo", {})
            assert exc_info.value.result.is_error is True
            assert exc_info.value.result.structured_content == {"ok": True}

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("client_class", "error_class"),
    [
        (
            type(
                "UnavailableClient",
                (FakeSdkClient,),
                {"__aenter__": lambda self: raise_async(OSError())},
            ),
            McpConnectionError,
        ),
        (
            type(
                "SlowClient",
                (FakeSdkClient,),
                {"__aenter__": lambda self: wait_forever()},
            ),
            McpTimeoutError,
        ),
    ],
)
def test_connection_failures_are_distinct(
    monkeypatch: pytest.MonkeyPatch,
    client_class: type[FakeSdkClient],
    error_class: type[Exception],
) -> None:
    monkeypatch.setattr(client_module, "Client", client_class)
    settings = Settings(
        mcp_services={
            "shopping": McpServiceConfig(
                url="http://127.0.0.1:8101/mcp", timeout_seconds=0.01
            )
        }
    )

    with pytest.raises(error_class):
        asyncio.run(McpClient(settings).connect("shopping").__aenter__())


async def raise_async(error: Exception) -> FakeSdkClient:
    raise error


async def wait_forever() -> FakeSdkClient:
    await asyncio.Event().wait()
    raise AssertionError("unreachable")