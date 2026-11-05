"""Read-only weather forecast queries over the configured Amap MCP service."""

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

MAX_CITY_LENGTH = 120
MAX_FORECASTS = 7
MAX_TEXT_LENGTH = 240


class WeatherQueryError(RuntimeError):
    """Raised when a weather query cannot be safely executed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


WEATHER_ERROR_MESSAGES = {
    "not_configured": "天气服务未配置。",
    "invalid_request": "天气查询参数无效。",
    "authentication_failed": "天气服务鉴权失败。",
    "protocol_error": "天气服务协议不兼容。",
    "rate_limited": "天气服务请求过于频繁，请稍后重试。",
    "timeout": "天气服务请求超时，请稍后重试。",
    "external_failure": "天气服务暂时失败，请稍后重试。",
}


def _error(code: str, message: str | None = None) -> WeatherQueryError:
    return WeatherQueryError(code, message or WEATHER_ERROR_MESSAGES[code])


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:MAX_TEXT_LENGTH] if value else None


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


def normalize_forecasts(payload: Any) -> list[dict[str, Any]]:
    """Keep only bounded, displayable forecast fields from untrusted MCP data."""
    if isinstance(payload, Mapping):
        forecasts = payload.get("forecasts", payload.get("forecast", []))
    else:
        forecasts = payload
    if not isinstance(forecasts, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in forecasts[:MAX_FORECASTS]:
        if not isinstance(item, Mapping):
            continue
        normalized.append(
            {
                "date": _text(item.get("date")),
                "week": _text(item.get("week")),
                "day_weather": _text(item.get("dayweather") or item.get("day_weather")),
                "night_weather": _text(
                    item.get("nightweather") or item.get("night_weather")
                ),
                "day_temperature": _text(item.get("daytemp") or item.get("day_temperature")),
                "night_temperature": _text(
                    item.get("nighttemp") or item.get("night_temperature")
                ),
                "day_wind": _text(item.get("daywind") or item.get("day_wind")),
                "night_wind": _text(item.get("nightwind") or item.get("night_wind")),
                "day_wind_power": _text(item.get("daypower") or item.get("day_wind_power")),
                "night_wind_power": _text(
                    item.get("nightpower") or item.get("night_wind_power")
                ),
            }
        )
    return normalized


async def query_weather(
    settings: Settings,
    city: str,
    *,
    service_id: str = "map",
    mcp_client: McpClient | None = None,
) -> dict[str, Any]:
    """Execute one configured, read-only weather query using the discovered tool."""
    city = city.strip()
    if not city or len(city) > MAX_CITY_LENGTH:
        raise _error("invalid_request")
    config = settings.mcp_services.get(service_id)
    if config is None or not config.enabled:
        raise _error("not_configured")
    tool_name = settings.map_mcp_weather_tool_name
    if tool_name not in config.allowed_tool_names:
        raise _error("protocol_error")
    client = mcp_client or McpClient(settings)
    try:
        async with client.connect(service_id) as connection:
            discovered = await connection.list_tools()
            matching = next((tool for tool in discovered if tool.name == tool_name), None)
            if matching is None:
                raise _error("protocol_error")
            discovered_tool = matching.tool if hasattr(matching, "tool") else matching
            schema = discovered_tool.input_schema or {}
            if schema.get("type") != "object" or "city" not in set(
                schema.get("required", ())
            ):
                raise _error("protocol_error")
            result = await connection.call_tool(tool_name, {"city": city})
    except WeatherQueryError:
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
    payload = _content_payload(result.result)
    forecasts = normalize_forecasts(payload)
    returned_city = (
        _text(payload.get("city")) if isinstance(payload, Mapping) else None
    ) or city
    return {
        "city": returned_city,
        "forecasts": forecasts,
        "source": {"service_id": service_id, "tool": tool_name, "simulated": False},
        "queried_at": datetime.now(UTC).isoformat(),
    }
