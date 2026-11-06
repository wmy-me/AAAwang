"""Small, trusted capability registry for selected shopping-task turns."""

import re
from dataclasses import dataclass
from enum import StrEnum


class RouteKind(StrEnum):
    DIRECT = "direct"
    CLARIFICATION = "clarification"
    CAPABILITIES = "capabilities"


@dataclass(frozen=True)
class CapabilitySpec:
    capability_id: str
    agent_id: str
    task_domain: str
    service_id: str
    allowed_tool_names: tuple[str, ...]
    read_only: bool
    result_type: str
    input_schema: dict[str, object]
    timeout_seconds: float
    model_budget_cost: int = 0
    remote_budget_cost: int = 1


@dataclass(frozen=True)
class CapabilityDecision:
    kind: RouteKind
    capability_ids: tuple[str, ...] = ()
    clarification: str | None = None
    parameters: dict[str, object] | None = None
    reason: str | None = None


_CAPABILITIES = {
    "shopping_product_discovery": CapabilitySpec(
        capability_id="shopping_product_discovery",
        agent_id="discovery",
        task_domain="shopping",
        service_id="shopping",
        allowed_tool_names=("search_products",),
        read_only=True,
        result_type="shopping_candidates",
        input_schema={"type": "object", "required": ["keyword"]},
        timeout_seconds=90.0,
    ),
    "map_place_search": CapabilitySpec(
        capability_id="map_place_search",
        agent_id="discovery",
        task_domain="shopping",
        service_id="map",
        allowed_tool_names=("maps_text_search", "maps_around_search", "maps_geo"),
        read_only=True,
        result_type="map_places",
        input_schema={"type": "object", "required": ["keywords"]},
        timeout_seconds=20.0,
    ),
    "weather_forecast": CapabilitySpec(
        capability_id="weather_forecast",
        agent_id="discovery",
        task_domain="shopping",
        service_id="map",
        allowed_tool_names=("maps_weather",),
        read_only=True,
        result_type="weather_forecast",
        input_schema={"type": "object", "required": ["city"]},
        timeout_seconds=20.0,
    ),
    "web_search": CapabilitySpec(
        capability_id="web_search",
        agent_id="discovery",
        task_domain="shopping",
        service_id="tavily",
        allowed_tool_names=("tavily_search",),
        read_only=True,
        result_type="web_search_results",
        input_schema={"type": "object", "required": ["query"]},
        timeout_seconds=30.0,
    ),
}

_MAP_PATTERN = re.compile(
    r"(地点|附近|周边|位置|地图|哪里买|礼品店)"
    r"|(?:(?:在|到|位于)\s*[^，。；;,\s]{2,20}?\s*(?:找|查|搜|看))"
)
_PRODUCT_PATTERN = re.compile(r"(买|购买|商品|预算|数量|人数|候选|采购)")
_WEATHER_PATTERN = re.compile(r"(天气|气温|温度|下雨|降雨|晴阴|预报)")
_CITY_PATTERN = re.compile(
    r"(?:在|到|位于)\s*([^，。；;,\s]{2,20}?)(?=\s*(?:找|查|搜|看|的|附近|周边|有|$))"
    r"|(?:查询|查找|搜索)\s*([一-鿿]{2,8}?)(?=(?:的)?(?:附近|周边|礼品|超市|商场|门店|店铺|地点|位置|店))"
    r"|(?:看看|看一下|查查|找找|查询|查找|搜索|找)\s*([一-鿿]{2,8}?)(?:市|区|县)?(?:附近|周边)"
    r"|([一-鿿]{2,8}?)(?:市|区|县)?(?:附近|周边)"
)
_WEATHER_CITY_PATTERN = re.compile(
    r"(?:查询|查|搜索|看看|看一下|了解|告诉我)?\s*"
    r"([一-鿿]{2,12}?)(?:市)?\s*(?:的)?\s*(?:天气|气温|温度|预报|会下雨)"
    r"|(?:天气|气温|温度|预报)\s*(?:查询|查|看)?\s*([一-鿿]{2,12}?)(?:市)?"
)
_WEATHER_NON_CITY_WORDS = {"怎么", "怎么样", "如何", "好吗", "可以吗"}
_WEB_SEARCH_PATTERN = re.compile(
    r"(搜索网页|网上查|网页资料|公开资料|最新信息|新闻|攻略|评测|口碑|知识|介绍|"
    r"研究|目的地|景点|怎么选|如何选择|推荐.*(?:网站|资料))"
)


def get_capability(capability_id: str) -> CapabilitySpec:
    """Return only a statically registered capability."""
    try:
        return _CAPABILITIES[capability_id]
    except KeyError as exc:
        raise ValueError(f"未注册能力: {capability_id}") from exc


def visible_capabilities(
    *,
    task_domain: str,
    enabled_services: set[str],
    discovered_tools: dict[str, dict[str, dict[str, object]]],
    agent_id: str = "discovery",
) -> tuple[CapabilitySpec, ...]:
    """Return the intersection of trusted policy and observed MCP tools.

    ``discovered_tools`` is deliberately a backend-owned snapshot keyed by
    service and tool name; model supplied URLs or tool names never enter this
    function.
    """
    visible: list[CapabilitySpec] = []
    for capability in _CAPABILITIES.values():
        if (
            capability.agent_id != agent_id
            or capability.task_domain != task_domain
            or not capability.read_only
            or capability.service_id not in enabled_services
        ):
            continue
        service_tools = discovered_tools.get(capability.service_id, {})
        if not any(
            tool_name in service_tools
            and _schema_compatible(capability.input_schema, service_tools[tool_name])
            for tool_name in capability.allowed_tool_names
        ):
            continue
        visible.append(capability)
    return tuple(visible)


def _schema_compatible(
    registered: dict[str, object], discovered: dict[str, object]
) -> bool:
    """Require the discovered schema to preserve registered required fields."""
    if registered.get("type") != discovered.get("type"):
        return False
    registered_required = set(registered.get("required", ()))
    discovered_required = set(discovered.get("required", ()))
    return registered_required <= discovered_required


def _has_city(text: str) -> bool:
    return any(match.groups() for match in _CITY_PATTERN.finditer(text))


def has_location_scope(text: str) -> bool:
    """Return whether the trusted location parser found a search scope."""
    return _has_city(text) or bool(re.search(r"\d{2,3}\.\d+\s*,\s*\d{1,2}\.\d+", text)) or bool(
        re.search(r"[^，。；;,\s]{2,80}(?:附近|周边)", text)
    )


def has_weather_city(text: str) -> bool:
    """Return whether a weather request names a city or adcode-like scope."""
    return any(
        any(group and group not in _WEATHER_NON_CITY_WORDS for group in match.groups())
        for match in _WEATHER_CITY_PATTERN.finditer(text)
    )


def route_task_turn(content: str, *, task_domain: str = "shopping") -> CapabilityDecision:
    """Choose trusted capabilities; model or user input cannot choose tools."""
    if task_domain != "shopping":
        return CapabilityDecision(RouteKind.CLARIFICATION, clarification="当前任务不支持购物能力。")
    text = content.strip()
    if not text:
        return CapabilityDecision(RouteKind.CLARIFICATION, clarification="请告诉我需要查询或购买什么。")
    wants_map = bool(_MAP_PATTERN.search(text))
    wants_product = bool(_PRODUCT_PATTERN.search(text))
    wants_weather = bool(_WEATHER_PATTERN.search(text))
    wants_web_search = bool(_WEB_SEARCH_PATTERN.search(text))
    capability_ids: list[str] = []
    if wants_map:
        if not _has_city(text):
            return CapabilityDecision(
                RouteKind.CLARIFICATION,
                clarification="请先告诉我需要查询的城市或位置范围。",
            )
        capability_ids.append("map_place_search")
    if wants_weather:
        if not has_weather_city(text):
            return CapabilityDecision(
                RouteKind.CLARIFICATION,
                clarification="请先告诉我需要查询天气的城市。",
            )
        capability_ids.append("weather_forecast")
    if wants_product:
        capability_ids.append("shopping_product_discovery")
    if wants_web_search:
        capability_ids.append("web_search")
    if not capability_ids:
        return CapabilityDecision(RouteKind.DIRECT)
    return CapabilityDecision(RouteKind.CAPABILITIES, tuple(capability_ids))
