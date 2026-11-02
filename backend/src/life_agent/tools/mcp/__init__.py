"""Generic MCP service discovery and tool invocation."""

from life_agent.tools.mcp.client import (
	DiscoveredTool,
	McpCallResult,
	McpClient,
	McpClientError,
	McpConnectionError,
	McpProtocolError,
	McpServiceConfigurationError,
	McpTimeoutError,
	McpToolExecutionError,
	McpToolNotFoundError,
)

__all__ = [
	"DiscoveredTool",
	"McpCallResult",
	"McpClient",
	"McpClientError",
	"McpConnectionError",
	"McpProtocolError",
	"McpServiceConfigurationError",
	"McpTimeoutError",
	"McpToolExecutionError",
	"McpToolNotFoundError",
]
"""Reserved for MCP client integrations (not implemented)."""
