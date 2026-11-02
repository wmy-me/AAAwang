"""Transport-neutral entry point for configured MCP services."""

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from mcp import Client
from mcp.types import CallToolResult, Tool

from life_agent.core.config import McpServiceConfig, Settings


class McpClientError(RuntimeError):
    """Base class for credential-safe MCP client errors."""


class McpServiceConfigurationError(McpClientError):
    """Raised for an unknown, disabled, or unsupported configured service."""


class McpConnectionError(McpClientError):
    """Raised when a configured MCP server cannot be reached."""


class McpProtocolError(McpClientError):
    """Raised when MCP initialization, discovery, or invocation fails."""


class McpTimeoutError(McpClientError):
    """Raised when an MCP operation exceeds its configured timeout."""


class McpToolNotFoundError(McpClientError):
    """Raised when a tool is not advertised by the selected service."""


class McpToolExecutionError(McpClientError):
    """Raised when the server returns an MCP tool error result."""

    def __init__(self, service_id: str, tool_name: str, result: CallToolResult) -> None:
        super().__init__(f"MCP 服务 {service_id} 的工具 {tool_name} 执行失败。")
        self.result = result


@dataclass(frozen=True)
class DiscoveredTool:
    """A tool identity plus the unmodified SDK tool description."""

    service_id: str
    name: str
    tool: Tool

    @property
    def qualified_name(self) -> str:
        return f"{self.service_id}:{self.name}"


@dataclass(frozen=True)
class McpCallResult:
    """A tool identity plus the unmodified SDK call result."""

    service_id: str
    tool_name: str
    result: CallToolResult


class McpConnection:
    """One initialized MCP session owned by an async context manager."""

    def __init__(
        self,
        service_id: str,
        config: McpServiceConfig,
        client: Client,
    ) -> None:
        self.service_id = service_id
        self.config = config
        self.client = client
        self._tools: dict[str, DiscoveredTool] | None = None

    @property
    def protocol_version(self) -> str:
        return self.client.protocol_version

    @property
    def server_info(self) -> Any:
        return self.client.server_info

    async def list_tools(self) -> list[DiscoveredTool]:
        try:
            async with asyncio.timeout(self.config.timeout_seconds):
                response = await self.client.list_tools()
        except TimeoutError as exc:
            raise McpTimeoutError(
                f"MCP 服务 {self.service_id} 工具发现超时。"
            ) from exc
        except Exception as exc:
            raise McpProtocolError(
                f"MCP 服务 {self.service_id} 工具发现失败。"
            ) from exc

        tools = [
            DiscoveredTool(self.service_id, tool.name, tool) for tool in response.tools
        ]
        self._tools = {tool.name: tool for tool in tools}
        return tools

    async def call_tool(
        self, tool_name: str, arguments: Mapping[str, Any]
    ) -> McpCallResult:
        if self._tools is None:
            await self.list_tools()
        if self._tools is None or tool_name not in self._tools:
            raise McpToolNotFoundError(
                f"MCP 服务 {self.service_id} 未发现工具 {tool_name}。"
            )

        try:
            async with asyncio.timeout(self.config.timeout_seconds):
                result = await self.client.call_tool(tool_name, dict(arguments))
        except TimeoutError as exc:
            raise McpTimeoutError(
                f"MCP 服务 {self.service_id} 调用工具 {tool_name} 超时。"
            ) from exc
        except Exception as exc:
            raise McpProtocolError(
                f"MCP 服务 {self.service_id} 调用工具 {tool_name} 时协议失败。"
            ) from exc

        if result.is_error:
            raise McpToolExecutionError(self.service_id, tool_name, result)
        return McpCallResult(self.service_id, tool_name, result)


class McpClient:
    """Connect to trusted MCP service definitions by service ID."""

    def __init__(self, settings: Settings) -> None:
        self._services = settings.mcp_services

    def _get_config(self, service_id: str) -> McpServiceConfig:
        config = self._services.get(service_id)
        if config is None:
            raise McpServiceConfigurationError(f"未知 MCP 服务 ID：{service_id}。")
        if not config.enabled:
            raise McpServiceConfigurationError(f"MCP 服务 {service_id} 未启用。")
        if config.transport != "streamable_http":
            raise McpServiceConfigurationError(
                f"MCP 服务 {service_id} 使用了不支持的传输类型。"
            )
        if config.auth_token is not None:
            raise McpServiceConfigurationError(
                f"MCP 服务 {service_id} 已配置认证，但本轮尚未实现认证传输。"
            )
        return config

    @asynccontextmanager
    async def connect(self, service_id: str) -> AsyncIterator[McpConnection]:
        config = self._get_config(service_id)
        sdk_client = Client(
            config.url,
            raise_exceptions=False,
            read_timeout_seconds=config.timeout_seconds,
            mode="auto",
        )
        try:
            async with asyncio.timeout(config.timeout_seconds):
                await sdk_client.__aenter__()
        except TimeoutError as exc:
            raise McpTimeoutError(f"MCP 服务 {service_id} 初始化超时。") from exc
        except (ConnectionError, OSError) as exc:
            raise McpConnectionError(f"无法连接 MCP 服务 {service_id}。") from exc
        except Exception as exc:
            raise McpProtocolError(f"MCP 服务 {service_id} 初始化失败。") from exc

        try:
            yield McpConnection(service_id, config, sdk_client)
        finally:
            await sdk_client.__aexit__(None, None, None)