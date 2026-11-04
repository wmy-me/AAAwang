import pytest

from life_agent.modules.chat.service import _is_map_request
from life_agent.worker.runner import _map_request


@pytest.mark.parametrize(
    ("text", "city", "query"),
    [
        ("在上海找附近的礼品店", "上海", "礼品店"),
        ("在上海找礼品店", "上海", "礼品店"),
        ("帮我在上海找礼品店", "上海", "礼品店"),
        ("到北京找附近的超市", "北京", "超市"),
        ("查询上海礼品店", "上海", "礼品店"),
        ("在上海市浦东新区找礼品店", "上海市浦东新区", "礼品店"),
        ("上海附近礼品店", "上海", "礼品店"),
        (
            "帮我看看上海附近的礼品店，并给25人购买奖品，预算200元",
            "上海",
            "礼品店",
        ),
        (
            "给25人购买奖品，预算200元；同时看看上海附近的礼品店",
            "上海",
            "礼品店",
        ),
        ("找礼品店", None, "礼品店"),
    ],
)
def test_map_request_extracts_city_and_query(
    text: str, city: str | None, query: str
) -> None:
    assert _map_request("", text) == (query, city)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("在上海找附近的礼品店", True),
        ("在上海找礼品店", True),
        ("查询上海礼品店", True),
        ("上海附近礼品店", True),
        ("帮我看看上海附近的礼品店，并给25人购买奖品，预算200元", True),
        ("给25人购买奖品，预算200元；同时看看上海附近的礼品店", True),
        ("到北京找附近超市", True),
        ("附近超市", True),
        ("帮我看看这些店铺的商品价格", False),
        ("这些奖品的预算是否足够", False),
        ("找超市", False),
    ],
)
def test_map_request_detection_requires_location_intent(
    text: str, expected: bool
) -> None:
    assert _is_map_request(text) is expected
