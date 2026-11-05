"""Read-only discovery entry points."""

from life_agent.agents.discovery.service import (
	ShoppingAgentResult,
	run_product_discovery,
)

__all__ = ["ShoppingAgentResult", "run_product_discovery"]
