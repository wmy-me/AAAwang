"""Read-only, bounded POI search over a configured map MCP service."""

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from life_agent.core.config import Settings
from life_agent.tools.mcp import McpClient

MAX_QUERY_LENGTH = 120
MAX_TEXT_LENGTH = 240
MAX_RESULTS = 20


class MapPlaceSearchError(RuntimeError):
    """Raised when a map query cannot be safely executed."""


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:MAX_TEXT_LENGTH] if value else None


def _items(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, Mapping):
        payload = payload.get("pois", payload.get("places", payload.get("results", [])))
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, Mapping)][:MAX_RESULTS]


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


def normalize_places(payload: Any, *, service_id: str, tool_name: str) -> list[dict[str, Any]]:
    """Keep only displayable POI fields; external text remains untrusted data."""
    return [
        {
            "name": _text(item.get("name") or item.get("title")),
            "address": _text(item.get("address") or item.get("formatted_address")),
            "location": _text(item.get("location") or item.get("coordinate")),
            "phone": _text(item.get("tel") or item.get("phone")),
            "url": _text(item.get("url") or item.get("website")),
            "source": {"service_id": service_id, "tool": tool_name},
        }
        for item in _items(payload)
    ]


async def search_places(
    settings: Settings,
    query: str,
    *,
    city: str | None = None,
    service_id: str = "map",
    mcp_client: McpClient | None = None,
) -> dict[str, Any]:
    """Execute one configured, read-only POI query without model-controlled routing."""
    query = query.strip()
    city = city.strip() if city else None
    if not query or len(query) > MAX_QUERY_LENGTH:
        raise MapPlaceSearchError("地点查询必须是 1 到 120 个字符。")
    if not city or len(city) > MAX_QUERY_LENGTH:
        raise MapPlaceSearchError("地点查询必须明确提供城市或位置范围。")
    config = settings.mcp_services.get(service_id)
    if config is None or not config.enabled:
        raise MapPlaceSearchError("地图服务未配置。")
    if len(config.allowed_tool_names) != 1:
        raise MapPlaceSearchError("地图服务必须配置一个只读地点工具。")
    tool_name = config.allowed_tool_names[0]
    client = mcp_client or McpClient(settings)
    try:
        async with client.connect(service_id) as connection:
            discovered = await connection.list_tools()
            if tool_name not in {tool.name for tool in discovered}:
                raise MapPlaceSearchError("地图地点工具未被服务公布。")
            result = await connection.call_tool(
                tool_name, {"keywords": query, "city": city, "citylimit": True}
            )
    except MapPlaceSearchError:
        raise
    except Exception as exc:
        raise MapPlaceSearchError("地图地点查询失败，请稍后重试。") from exc
    return {
        "places": normalize_places(
            _content_payload(result.result),
            service_id=service_id,
            tool_name=tool_name,
        ),
        "source": {"service_id": service_id, "tool": tool_name, "simulated": False},
        "observed_at": datetime.now(UTC).isoformat(),
    }