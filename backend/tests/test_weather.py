import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from mcp.types import CallToolResult, Tool

from life_agent.core.config import McpServiceConfig, Settings
from life_agent.tools.maps import WeatherQueryError, normalize_forecasts, query_weather
from life_agent.tools.mcp import McpAuthenticationError
from life_agent.worker.runner import _weather_city


def configured_settings() -> Settings:
    return Settings(
        _env_file=None,
        mcp_services={
            "map": McpServiceConfig(
                url="https://mcp.example/mcp",
                allowed_tool_names=("maps_weather",),
            )
        },
    )


class WeatherConnection:
    async def list_tools(self) -> list[Any]:
        return [
            Tool(
                name="maps_weather",
                inputSchema={"type": "object", "required": ["city"]},
            )
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        assert name == "maps_weather"
        assert arguments == {"city": "上海"}
        return SimpleNamespace(
            result=CallToolResult(
                content=[],
                structuredContent={
                    "city": "上海",
                    "forecasts": [
                        {
                            "date": "2026-11-06",
                            "dayweather": "晴",
                            "nightweather": "多云",
                            "daytemp": "20",
                            "nighttemp": "12",
                            "daywind": "东",
                            "unexpected": "drop me",
                        }
                    ],
                },
                isError=False,
            )
        )


class FakeClient:
    @asynccontextmanager
    async def connect(self, _service_id: str) -> Any:
        yield WeatherConnection()


def test_normalize_forecasts_bounds_and_allowlists_fields() -> None:
    result = normalize_forecasts(
        [{"date": "2026-11-06", "dayweather": "晴", "extra": "drop me"}] * 10
    )
    assert len(result) == 7
    assert result[0]["day_weather"] == "晴"
    assert "extra" not in result[0]


def test_query_weather_calls_discovered_allowlisted_tool() -> None:
    result = asyncio.run(
        query_weather(configured_settings(), "上海", mcp_client=FakeClient())
    )
    assert result["city"] == "上海"
    assert result["source"]["tool"] == "maps_weather"
    assert result["forecasts"][0]["night_temperature"] == "12"


def test_query_weather_rejects_missing_city_before_mcp() -> None:
    with pytest.raises(WeatherQueryError) as error:
        asyncio.run(query_weather(configured_settings(), ""))
    assert error.value.code == "invalid_request"


def test_query_weather_maps_authentication_error() -> None:
    class RaisingConnection(WeatherConnection):
        async def list_tools(self) -> list[Any]:
            raise McpAuthenticationError()

    class RaisingClient(FakeClient):
        @asynccontextmanager
        async def connect(self, _service_id: str) -> Any:
            yield RaisingConnection()

    with pytest.raises(WeatherQueryError) as error:
        asyncio.run(
            query_weather(configured_settings(), "上海", mcp_client=RaisingClient())
        )
    assert error.value.code == "authentication_failed"


def test_weather_city_parser_removes_request_prefix() -> None:
    assert _weather_city("查询城市天气", "请查询上海天气") == "上海"
    assert _weather_city("查询城市天气", "北京的天气") == "北京"
