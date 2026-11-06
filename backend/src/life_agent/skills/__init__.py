"""Registered, bounded guidance assets used by Agent roles."""

from life_agent.skills.loader import (
    SkillDefinition,
    available_skills,
    register_skill,
    select_skill,
    shopping_guidance,
    skill_context,
)

__all__ = [
    "SkillDefinition",
    "available_skills",
    "register_skill",
    "select_skill",
    "shopping_guidance",
    "skill_context",
]
