"""Trusted coordinator entry points for bounded Run decisions.

The coordinator owns the public boundary for model routing. Worker lifecycle,
leases and terminal persistence remain outside this module.
"""

from typing import Any


def decide_capabilities(settings: Any, claim: Any, budget: Any) -> dict[str, object]:
    """Produce one validated capability decision for the current Run.

    The implementation is injected through the legacy worker adapter during
    this migration so old tests and Run contracts stay compatible. The public
    call boundary belongs to the coordinator package.
    """
    from life_agent.worker.runner import _run_capability_decision_impl

    return _run_capability_decision_impl(settings, claim, budget)
