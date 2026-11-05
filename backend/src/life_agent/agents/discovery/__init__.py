"""Read-only discovery entry points."""

from life_agent.agents.discovery.service import (
    ShoppingAgentResult,
    build_shopping_prompt,
    run_product_discovery,
)

__all__ = ["ShoppingAgentResult", "build_shopping_prompt", "run_product_discovery"]
