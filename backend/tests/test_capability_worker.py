from types import SimpleNamespace

import pytest

from life_agent.core.llm import ToolLoopError
from life_agent.modules.runs.service import _map_source
from life_agent.worker.runner import _validate_claim_capabilities


def claim(execution_type: str, capability_ids: tuple[str, ...]):
    return SimpleNamespace(
        execution_type=execution_type,
        capability_ids=capability_ids,
    )


def test_worker_accepts_registered_matching_capability() -> None:
    _validate_claim_capabilities(
        claim("map_places", ("map_place_search",))
    )


def test_worker_rejects_cross_capability_execution() -> None:
    with pytest.raises(ToolLoopError, match="商品 Run 的能力快照无效"):
        _validate_claim_capabilities(
            claim("shopping_agent", ("map_place_search",))
        )


def test_worker_rejects_unknown_capability() -> None:
    with pytest.raises(ValueError, match="未注册能力"):
        _validate_claim_capabilities(claim("map_places", ("unknown",)))


def test_worker_accepts_combined_read_only_capabilities() -> None:
    _validate_claim_capabilities(
        claim(
            "capability_router",
            ("map_place_search", "shopping_product_discovery"),
        )
    )


def test_worker_rejects_unapproved_capability_combination() -> None:
    with pytest.raises(ValueError, match="未注册能力"):
        _validate_claim_capabilities(
            claim("capability_router", ("map_place_search", "unknown"))
        )


def test_combined_run_keeps_map_source_separate() -> None:
    source = _map_source(
        {
            "source": {"service_id": "shopping", "tool": "search_products"},
            "map_source": {"service_id": "map", "tool": "maps_text_search"},
        }
    )
    assert source == {"service_id": "map", "tool": "maps_text_search"}


def test_map_only_run_falls_back_to_its_source() -> None:
    source = _map_source(
        {"source": {"service_id": "map", "tool": "maps_text_search"}}
    )
    assert source == {"service_id": "map", "tool": "maps_text_search"}
