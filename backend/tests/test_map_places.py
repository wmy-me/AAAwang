import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, Self

import pytest
from mcp.types import CallToolResult, Tool
from pydantic import SecretStr

from life_agent.core.config import McpServiceConfig, Settings
from life_agent.tools.maps import MapPlaceSearchError, normalize_places, search_places
from life_agent.tools.mcp import McpClient


class FakeConnection:
    async def list_tools(self) -> list[Any]:
        return [Tool(name="search_poi", inputSchema={"type": "object"})]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        assert name == "search_poi"
        assert arguments == {
            "keywords": "礼品店",
            "city": "上海",
            "citylimit": True,
        }
        return SimpleNamespace(
            result=CallToolResult(
                content=[],
                structuredContent={
                    "pois": [
                        {
                            "name": "示例店",
                            "address": "示例路 1 号",
                            "location": "121.4,31.2",
                            "unexpected": "drop me",
                        }
                    ]
                },
                isError=False,
            )
        )


class FakeMcpClient:
    @asynccontextmanager
    async def connect(self, _service_id: str) -> Any:
        yield FakeConnection()


def configured_settings() -> Settings:
    return Settings(
        _env_file=None,
        mcp_services={
            "map": McpServiceConfig(
                url="https://mcp.example/mcp",
                allowed_tool_names=("search_poi",),
            )
        }
    )


def test_missing_city_is_rejected_before_mcp_call() -> None:
    with pytest.raises(MapPlaceSearchError, match="明确提供城市"):
        asyncio.run(search_places(configured_settings(), "礼品店", mcp_client=FakeMcpClient()))


def test_unconfigured_map_is_distinct() -> None:
    settings = configured_settings().model_copy(update={"mcp_services": {}})
    with pytest.raises(MapPlaceSearchError, match="地图服务未配置"):
        asyncio.run(
            search_places(settings, "礼品店", city="上海", mcp_client=FakeMcpClient())
        )


def test_poi_fields_are_allowlisted_and_source_is_attached() -> None:
    result = asyncio.run(
        search_places(
            configured_settings(),
            "礼品店",
            city="上海",
            mcp_client=FakeMcpClient(),
        )
    )
    assert result["places"] == [
        {
            "name": "示例店",
            "address": "示例路 1 号",
            "location": "121.4,31.2",
            "phone": None,
            "url": None,
            "source": {"service_id": "map", "tool": "search_poi"},
        }
    ]
    assert result["source"]["simulated"] is False
    assert "observed_at" in result


def test_normalize_places_limits_text_and_unknown_payload() -> None:
    result = normalize_places(
        {"results": [{"title": "x" * 500, "website": "https://example.test"}]},
        service_id="map",
        tool_name="search_poi",
    )
    assert len(result[0]["name"]) == 240
    assert normalize_places({"unexpected": "shape"}, service_id="map", tool_name="search_poi") == []


def test_authentication_query_parameter_is_added_without_preconfigured_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    class FakeSdkClient:
        def __init__(self, url: str, **_kwargs: Any) -> None:
            captured["url"] = url

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    import life_agent.tools.mcp.client as client_module

    monkeypatch.setattr(client_module, "Client", FakeSdkClient)
    settings = Settings(
        _env_file=None,
        mcp_services={
            "map": McpServiceConfig(
                url="https://mcp.example/mcp?tenant=demo",
                auth_token=SecretStr("secret-value"),
                auth_query_parameter="key",
            )
        }
    )
    async def connect() -> None:
        async with McpClient(settings).connect("map"):
            pass

    asyncio.run(connect())
    assert captured["url"] == "https://mcp.example/mcp?tenant=demo&key=secret-value"