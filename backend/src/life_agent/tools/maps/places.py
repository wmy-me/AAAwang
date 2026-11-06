"""Read-only, bounded POI search over a configured map MCP service."""

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

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

MAX_QUERY_LENGTH = 120
MAX_TEXT_LENGTH = 240
MAX_RESULTS = 20
DEFAULT_NEARBY_RADIUS_METERS = 1000


class MapPlaceSearchError(RuntimeError):
    """Raised when a map query cannot be safely executed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


MAP_ERROR_MESSAGES = {
    "not_configured": "地图服务未配置。",
    "invalid_request": "地点查询参数无效。",
    "authentication_failed": "地图服务鉴权失败。",
    "protocol_error": "地图服务协议不兼容。",
    "rate_limited": "地图服务请求过于频繁，请稍后重试。",
    "timeout": "地图服务请求超时，请稍后重试。",
    "external_failure": "地图服务暂时失败，请稍后重试。",
}


def _error(code: str, message: str | None = None) -> MapPlaceSearchError:
    return MapPlaceSearchError(code, message or MAP_ERROR_MESSAGES[code])


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:MAX_TEXT_LENGTH] if value else None


def _items(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, Mapping):
        payload = payload.get("pois", payload.get("geocodes", payload.get("places", payload.get("results", []))))
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
        raise _error("invalid_request")
    if not city or len(city) > MAX_QUERY_LENGTH:
        raise _error("invalid_request", "地点查询必须明确提供城市或位置范围。")
    config = settings.mcp_services.get(service_id)
    if config is None or not config.enabled:
        raise _error("not_configured")
    tool_name = settings.map_mcp_tool_name
    if tool_name not in config.allowed_tool_names and len(config.allowed_tool_names) == 1:
        tool_name = config.allowed_tool_names[0]
    if tool_name not in config.allowed_tool_names:
        raise _error("protocol_error")
    client = mcp_client or McpClient(settings)
    try:
        async with client.connect(service_id) as connection:
            discovered = await connection.list_tools()
            if tool_name not in {tool.name for tool in discovered}:
                raise _error("protocol_error")
            result = await connection.call_tool(
                tool_name, {"keywords": query, "city": city, "citylimit": True}
            )
    except MapPlaceSearchError:
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
    return {
        "places": normalize_places(
            _content_payload(result.result),
            service_id=service_id,
            tool_name=tool_name,
        ),
        "source": {"service_id": service_id, "tool": tool_name, "simulated": False},
        "observed_at": datetime.now(UTC).isoformat(),
    }


def _allowed_tool(settings: Settings, service_id: str, configured_name: str) -> str:
    config = settings.mcp_services.get(service_id)
    if config is None or not config.enabled:
        raise _error("not_configured")
    tool_name = configured_name.strip()
    if not tool_name or tool_name not in config.allowed_tool_names:
        raise _error("protocol_error")
    return tool_name


async def geocode_address(settings: Settings, address: str, *, service_id: str = "map", mcp_client: McpClient | None = None) -> str:
    """Resolve one unambiguous user-supplied address to a coordinate string."""
    address = address.strip()
    if not address or len(address) > MAX_QUERY_LENGTH:
        raise _error("invalid_request")
    tool_name = _allowed_tool(settings, service_id, settings.map_mcp_geocode_tool_name)
    client = mcp_client or McpClient(settings)
    try:
        async with client.connect(service_id) as connection:
            if tool_name not in {tool.name for tool in await connection.list_tools()}:
                raise _error("protocol_error")
            result = await connection.call_tool(tool_name, {"address": address})
    except MapPlaceSearchError:
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
    candidates = _items(_content_payload(result.result))
    locations = {_text(item.get("location") or item.get("coordinate")) for item in candidates}
    locations.discard(None)
    if len(locations) != 1:
        raise _error("invalid_request", "地址无法唯一定位，请补充更具体的位置或直接提供坐标。")
    return next(iter(locations))


async def search_nearby_places(
    settings: Settings, query: str, *, location: str, radius_meters: int | None = None,
    service_id: str = "map", mcp_client: McpClient | None = None,
) -> dict[str, Any]:
    """Search POIs around a server-validated coordinate, not a city query."""
    query, location = query.strip(), location.strip()
    if not query or len(query) > MAX_QUERY_LENGTH or not _coordinate(location):
        raise _error("invalid_request")
    radius = radius_meters if radius_meters is not None else settings.map_mcp_nearby_radius_meters
    if not isinstance(radius, int) or not 100 <= radius <= 50000:
        raise _error("invalid_request")
    tool_name = _allowed_tool(settings, service_id, settings.map_mcp_nearby_tool_name)
    client = mcp_client or McpClient(settings)
    try:
        async with client.connect(service_id) as connection:
            if tool_name not in {tool.name for tool in await connection.list_tools()}:
                raise _error("protocol_error")
            result = await connection.call_tool(tool_name, {"keywords": query, "location": location, "radius": str(radius), "strategy": 0})
    except MapPlaceSearchError:
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
    return {
        "places": normalize_places(_content_payload(result.result), service_id=service_id, tool_name=tool_name),
        "source": {"service_id": service_id, "tool": tool_name, "simulated": False},
        "observed_at": datetime.now(UTC).isoformat(), "location": location, "radius_meters": radius,
    }


def _coordinate(value: str) -> bool:
    try:
        longitude, latitude = (float(part.strip()) for part in value.split(",", 1))
    except (TypeError, ValueError):
        return False
    return -180 <= longitude <= 180 and -90 <= latitude <= 90
