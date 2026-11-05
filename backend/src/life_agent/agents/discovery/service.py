"""Bounded read-only discovery entry points.

This package adapts the existing shopping graph and MCP-backed map adapter;
it does not own Run leases or persistence.
"""

from typing import Any

from life_agent.agents.shopping import ShoppingAgentResult, run_shopping_agent

__all__ = ["ShoppingAgentResult", "run_product_discovery", "run_shopping_agent"]


async def run_product_discovery(
    settings: Any,
    goal: str,
    conditions: dict[str, object],
    *,
    model_client: Any = None,
    discovery_model_client: Any = None,
    mcp_client: Any = None,
    force_discovery: bool = False,
    budget: Any = None,
) -> ShoppingAgentResult:
    """Run the bounded product discovery graph with one shared Run budget."""
    return await run_shopping_agent(
        settings,
        goal,
        conditions,
        model_client=model_client,
        discovery_model_client=discovery_model_client,
        mcp_client=mcp_client,
        force_discovery=force_discovery,
        budget=budget,
    )
