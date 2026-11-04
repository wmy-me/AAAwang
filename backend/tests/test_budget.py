import threading

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