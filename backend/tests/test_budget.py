import threading
from datetime import UTC, datetime, timedelta

import pytest

from life_agent.core.budget import BudgetExceededError, BudgetLimits, RunBudget


def test_budget_reserves_failures_and_tracks_mcp_as_remote_call() -> None:
    budget = RunBudget(BudgetLimits(model_requests=1, mcp_attempts=1, remote_calls=1))

    budget.reserve("model")
    with pytest.raises(BudgetExceededError, match="model_budget_exhausted"):
        budget.reserve("model")

    assert budget.snapshot()["model_requests"] == 1


def test_budget_rejects_mcp_after_shared_remote_limit() -> None:
    budget = RunBudget(BudgetLimits(mcp_attempts=2, remote_calls=1))

    budget.reserve("mcp")
    with pytest.raises(BudgetExceededError, match="remote_budget_exhausted"):
        budget.reserve("mcp")
    assert budget.snapshot()["mcp_attempts"] == 1


def test_budget_reservation_is_shared_across_concurrent_branches() -> None:
    budget = RunBudget(BudgetLimits(mcp_attempts=2, remote_calls=2))
    errors: list[Exception] = []

    def reserve() -> None:
        try:
            budget.reserve("mcp")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=reserve) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert budget.snapshot()["mcp_attempts"] == 2
    assert len(errors) == 3


def test_budget_stop_blocks_new_reservations() -> None:
    budget = RunBudget()
    budget.stop("cancelled")

    with pytest.raises(BudgetExceededError, match="cancelled"):
        budget.reserve("model")


def test_discovery_consumes_shared_remote_limit() -> None:
    budget = RunBudget(BudgetLimits(mcp_attempts=1, remote_calls=1))

    budget.reserve("discovery")

    with pytest.raises(BudgetExceededError, match="remote_budget_exhausted"):
        budget.reserve("mcp")
    snapshot = budget.snapshot()
    assert snapshot["mcp_attempts"] == 0
    assert snapshot["remote_calls"] == 1


def test_budget_records_wall_clock_timeout_before_new_call() -> None:
    budget = RunBudget(
        BudgetLimits(wall_clock_seconds=0.01),
        started_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    with pytest.raises(BudgetExceededError, match="timeout"):
        budget.reserve("mcp")

    assert budget.snapshot()["termination_reason"] == "timeout"


def test_budget_restores_persisted_route_reservation() -> None:
    budget = RunBudget(BudgetLimits(model_requests=2))
    budget.reserve("model")
    restored = RunBudget.from_snapshot(budget.snapshot())
    restored.reserve("model")
    with pytest.raises(BudgetExceededError, match="model_budget_exhausted"):
        restored.reserve("model")


def test_every_external_reservation_is_persisted_before_the_attempt() -> None:
    snapshots: list[dict[str, object]] = []
    budget = RunBudget(on_reserve=lambda snapshot: snapshots.append(snapshot))
    for kind in ("model", "discovery", "delegation", "mcp"):
        budget.reserve(kind)
    assert [snapshot["model_requests"] for snapshot in snapshots] == [1, 1, 1, 1]
    assert snapshots[-1]["delegations"] == 1
    assert snapshots[-1]["mcp_attempts"] == 1
    assert snapshots[-1]["remote_calls"] == 2
