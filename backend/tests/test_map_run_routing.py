import pytest

from life_agent.worker.runner import _map_request


@pytest.mark.parametrize(
    ("text", "city", "query"),
    [
        ("在上海找附近的礼品店", "上海", "礼品店"),
        ("帮我在上海找礼品店", "上海", "礼品店"),
        ("到北京找附近的超市", "北京", "超市"),
        ("查询上海礼品店", "上海", "礼品店"),
        ("在上海市浦东新区找礼品店", "上海市浦东新区", "礼品店"),
        ("上海附近礼品店", "上海", "礼品店"),
        ("找礼品店", None, "礼品店"),
    ],
)
def test_map_request_extracts_city_and_query(
    text: str, city: str | None, query: str
) -> None:
    assert _map_request("", text) == (query, city)
