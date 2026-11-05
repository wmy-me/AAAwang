"""Bounded read-only discovery entry points.

This package adapts the existing shopping graph and MCP-backed map adapter;
it does not own Run leases or persistence.
"""

from typing import Any

from life_agent.agents.discovery.graph import ShoppingAgentResult, run_shopping_agent
from life_agent.agents.shared.skill_loader import skill_context

__all__ = [
    "ShoppingAgentResult",
    "build_shopping_prompt",
    "run_product_discovery",
    "run_shopping_agent",
]


def build_shopping_prompt(goal: str, conditions: dict[str, object]) -> str:
    """Build the bounded product-discovery prompt without platform details."""
    known = ", ".join(f"{key}={value}" for key, value in conditions.items()) or "无"
    return (
        f"购物目标：{goal}\n已知条件：{known}\n"
        f"{skill_context(f'{goal} {known}')}\n"
        "只查询并回答模拟商品候选。未提供的预算、物品、数量必须明确写为未知，不能猜测。"
    )


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
