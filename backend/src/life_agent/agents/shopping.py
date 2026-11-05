"""Compatibility exports for the former shopping graph module.

The single production implementation now lives in ``discovery.graph``.
"""

from life_agent.agents.discovery.graph import ShoppingAgentResult, run_shopping_agent

__all__ = ["ShoppingAgentResult", "run_shopping_agent"]
