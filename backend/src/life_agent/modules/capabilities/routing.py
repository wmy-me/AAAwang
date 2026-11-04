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


@dataclass(frozen=True)
class CapabilityDecision:
    kind: RouteKind
    capability_ids: tuple[str, ...] = ()
    clarification: str | None = None


_CAPABILITIES = {
    "shopping_product_discovery": CapabilitySpec(
        capability_id="shopping_product_discovery",
        agent_id="discovery",
        task_domain="shopping",
        service_id="shopping",
        allowed_tool_names=("search_products",),
        read_only=True,
        result_type="shopping_candidates",
    ),
    "map_place_search": CapabilitySpec(
        capability_id="map_place_search",
        agent_id="discovery",
        task_domain="shopping",
        service_id="map",
        allowed_tool_names=("maps_text_search",),
        read_only=True,
        result_type="map_places",
    ),
}

_MAP_PATTERN = re.compile(
    r"(地点|附近|周边|位置|地图|哪里买|礼品店)"
    r"|(?:(?:在|到|位于)\s*[^，。；;,\s]{2,20}?\s*(?:找|查|搜|看))"
)
_PRODUCT_PATTERN = re.compile(r"(买|购买|商品|奖品|彩色铅笔|预算|数量|人数|候选|采购)")
_CITY_PATTERN = re.compile(
    r"(?:在|到|位于)\s*([^，。；;,\s]{2,20}?)(?=\s*(?:找|查|搜|看|的|附近|周边|有|$))"
    r"|(?:查询|查找|搜索)\s*([一-鿿]{2,8}?)(?=(?:的)?(?:附近|周边|礼品|超市|商场|门店|店铺|地点|位置|店))"
    r"|(?:看看|看一下|查查|找找|查询|查找|搜索|找)\s*([一-鿿]{2,8}?)(?:市|区|县)?(?:附近|周边)"
    r"|([一-鿿]{2,8}?)(?:市|区|县)?(?:附近|周边)"
)


def get_capability(capability_id: str) -> CapabilitySpec:
    """Return only a statically registered capability."""
    try:
        return _CAPABILITIES[capability_id]
    except KeyError as exc:
        raise ValueError(f"未注册能力: {capability_id}") from exc


def _has_city(text: str) -> bool:
    return any(match.groups() for match in _CITY_PATTERN.finditer(text))


def route_task_turn(content: str, *, task_domain: str = "shopping") -> CapabilityDecision:
    """Choose trusted capabilities; model or user input cannot choose tools."""
    if task_domain != "shopping":
        return CapabilityDecision(RouteKind.CLARIFICATION, clarification="当前任务不支持购物能力。")
    text = content.strip()
    if not text:
        return CapabilityDecision(RouteKind.CLARIFICATION, clarification="请告诉我需要查询或购买什么。")
    wants_map = bool(_MAP_PATTERN.search(text))
    wants_product = bool(_PRODUCT_PATTERN.search(text))
    capability_ids: list[str] = []
    if wants_map:
        if not _has_city(text):
            return CapabilityDecision(
                RouteKind.CLARIFICATION,
                clarification="请先告诉我需要查询的城市或位置范围。",
            )
        capability_ids.append("map_place_search")
    if wants_product:
        capability_ids.append("shopping_product_discovery")
    if not capability_ids:
        return CapabilityDecision(RouteKind.DIRECT)
    return CapabilityDecision(RouteKind.CAPABILITIES, tuple(capability_ids))