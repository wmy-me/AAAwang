import pytest

from life_agent.modules.capabilities import (
    RouteKind,
    get_capability,
    route_task_turn,
    visible_capabilities,
)


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("买彩色铅笔作为奖品", (RouteKind.CAPABILITIES, ("shopping_product_discovery",))),
        ("在上海找礼品店", (RouteKind.CAPABILITIES, ("map_place_search",))),
        (
            "在上海找礼品店并给我推荐奖品",
            (RouteKind.CAPABILITIES, ("map_place_search", "shopping_product_discovery")),
        ),
        ("帮我看看", (RouteKind.DIRECT, ())),
    ],
)
def test_route_task_turn_selects_registered_capabilities(content, expected) -> None:
    decision = route_task_turn(content)
    assert (decision.kind, decision.capability_ids) == expected


def test_map_request_without_city_asks_before_calling() -> None:
    decision = route_task_turn("找一家礼品店")
    assert decision.kind is RouteKind.CLARIFICATION
    assert decision.capability_ids == ()


def test_unregistered_capability_is_rejected() -> None:
    with pytest.raises(ValueError, match="未注册能力"):
        get_capability("arbitrary_url_tool")


def test_registered_capabilities_are_read_only_and_allowlisted() -> None:
    assert get_capability("map_place_search").read_only is True
    assert get_capability("map_place_search").allowed_tool_names == ("maps_text_search",)
    assert get_capability("map_place_search").timeout_seconds > 0


def test_visible_capabilities_require_configured_and_discovered_intersection() -> None:
    discovered = {
        "map": {"maps_text_search": {"type": "object"}},
        "shopping": {"other_tool": {"type": "object"}},
    }

    visible = visible_capabilities(
        task_domain="shopping",
        enabled_services={"map", "shopping"},
        discovered_tools=discovered,
    )

    assert tuple(spec.capability_id for spec in visible) == ("map_place_search",)


def test_visible_capabilities_reject_schema_incompatibility_and_disabled_service() -> None:
    visible = visible_capabilities(
        task_domain="shopping",
        enabled_services={"shopping"},
        discovered_tools={
            "shopping": {"search_products": {"type": "array"}},
            "map": {"maps_text_search": {"type": "object"}},
        },
    )

    assert visible == ()
