"""Trusted capability registration and task-turn routing."""

from life_agent.modules.capabilities.routing import (
    CapabilityDecision,
    CapabilitySpec,
    RouteKind,
    get_capability,
    route_task_turn,
    visible_capabilities,
)

__all__ = [
    "CapabilityDecision",
    "CapabilitySpec",
    "RouteKind",
    "get_capability",
    "route_task_turn",
    "visible_capabilities",
]
