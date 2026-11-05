"""Bounded public web search over the configured Tavily MCP service."""

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from life_agent.core.config import Settings
from life_agent.tools.mcp import (
    McpAuthenticationError,
    McpClient,
    McpConnectionError,
    McpProtocolError,
    McpRateLimitError,
    McpTimeoutError,
    McpToolExecutionError,
    McpToolNotFoundError,
)

MAX_QUERY_LENGTH = 500
MAX_RESULTS = 10
MAX_TEXT_LENGTH = 1000


class WebSearchError(RuntimeError):
    """Raised when a public web search cannot be safely completed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


WEB_SEARCH_ERROR_MESSAGES = {
    "not_configured": "网页搜索服务未配置或未启用。",
    "invalid_request": "网页搜索问题无效。",
    "authentication_failed": "网页搜索服务鉴权失败。",
    "protocol_error": "网页搜索服务协议不兼容。",
    "rate_limited": "网页搜索服务请求过于频繁，请稍后重试。",
    "timeout": "网页搜索服务请求超时，请稍后重试。",
    "external_failure": "网页搜索服务暂时失败，请稍后重试。",
}


def _error(code: str, message: str | None = None) -> WebSearchError:
    return WebSearchError(code, message or WEB_SEARCH_ERROR_MESSAGES[code])


def _text(value: Any, limit: int = MAX_TEXT_LENGTH) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:limit] if value else None


def _content_payload(result: Any) -> Any:
    structured = result.structured_content
    if structured is not None:
        return structured
    for item in result.content:
        text = getattr(item, "text", None)
        if not isinstance(text, str):
            continue
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            continue
    return None


def _items(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, Mapping):
        payload = payload.get("results", payload.get("data", []))
    return [item for item in payload[:MAX_RESULTS] if isinstance(item, Mapping)] if isinstance(payload, list) else []


def _public_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    host = parsed.hostname or ""
    if host.casefold() in {"localhost", "127.0.0.1", "::1"}:
        return None
    if host.startswith(("10.", "192.168.", "169.254.")):
        return None
    if host.startswith("172."):
        try:
            if 16 <= int(host.split(".")[1]) <= 31:
                return None
        except (IndexError, ValueError):
            return None
    return value[:2000]


def normalize_search_results(
    payload: Any, *, service_id: str, tool_name: str, observed_at: str
) -> list[dict[str, Any]]:
    """Keep bounded source metadata; web text remains untrusted evidence."""
    normalized: list[dict[str, Any]] = []
    for item in _items(payload):
        url = _public_url(item.get("url") or item.get("link"))
        if url is None:
            continue
        normalized.append(
            {
                "title": _text(item.get("title") or item.get("name"), 300) or "未命名来源",
                "url": url,
                "summary": _text(item.get("content") or item.get("snippet") or item.get("raw_content")),
                "published_at": _text(item.get("published_date") or item.get("published_at"), 80),
                "source_service": service_id,
                "source_tool": tool_name,
                "observed_at": observed_at,
            }
        )
    return normalized


async def search_web(
    settings: Settings,
    query: str,
    *,
    service_id: str = "tavily",
    mcp_client: McpClient | None = None,
) -> dict[str, Any]:
    """Execute one configured, read-only web search with source validation."""
    query = query.strip()
    if not query or len(query) > MAX_QUERY_LENGTH:
        raise _error("invalid_request")
    config = settings.mcp_services.get(service_id)
    if config is None or not config.enabled:
        raise _error("not_configured")
    tool_name = settings.tavily_mcp_tool_name
    if tool_name not in config.allowed_tool_names:
        raise _error("protocol_error")
    client = mcp_client or McpClient(settings)
    try:
        async with client.connect(service_id) as connection:
            discovered = await connection.list_tools()
            matching = next((tool for tool in discovered if tool.name == tool_name), None)
            if matching is None:
                raise _error("protocol_error")
            schema = matching.tool.input_schema or {}
            if schema.get("type") != "object" or "query" not in set(schema.get("required", ())):
                raise _error("protocol_error")
            result = await connection.call_tool(tool_name, {"query": query, "max_results": MAX_RESULTS})
    except WebSearchError:
        raise
    except McpAuthenticationError as exc:
        raise _error("authentication_failed") from exc
    except McpRateLimitError as exc:
        raise _error("rate_limited") from exc
    except McpTimeoutError as exc:
        raise _error("timeout") from exc
    except (McpProtocolError, McpToolNotFoundError) as exc:
        raise _error("protocol_error") from exc
    except (McpConnectionError, McpToolExecutionError) as exc:
        raise _error("external_failure") from exc
    except Exception as exc:
        raise _error("external_failure") from exc
    observed_at = datetime.now(UTC).isoformat()
    payload = _content_payload(result.result)
    return {
        "query": query,
        "results": normalize_search_results(
            payload, service_id=service_id, tool_name=tool_name, observed_at=observed_at
        ),
        "source": {"service_id": service_id, "tool": tool_name, "simulated": False},
        "observed_at": observed_at,
    }
