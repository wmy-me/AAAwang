"""Deterministic procurement boundary.

This is deliberately not a second ReAct agent. Candidate normalization,
amount calculation and plan validation remain pure application services.
"""

from typing import Any

from life_agent.modules.shopping_plans.service import (
    build_artifacts,
    validated_plan_answer,
)

__all__ = ["build_artifacts", "build_validated_plan", "validated_plan_answer"]


def build_validated_plan(
    source: dict[str, object], conditions: dict[str, object]
) -> tuple[dict[str, Any], str | None]:
    """Normalize evidence, deterministically validate a plan, and render it."""
    artifacts = build_artifacts(source, conditions)
    return artifacts, validated_plan_answer(artifacts)
