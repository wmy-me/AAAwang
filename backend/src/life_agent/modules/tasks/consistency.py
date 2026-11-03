"""Deterministic checks for explicit shopping goal/condition conflicts."""

import re
from dataclasses import dataclass

from life_agent.modules.tasks.schemas import Conditions


@dataclass(frozen=True)
class GoalConsistency:
    conflicts: list[dict[str, object]]
    uncertain: list[dict[str, object]]

    @property
    def has_conflict(self) -> bool:
        return bool(self.conflicts)


class GoalConflictError(ValueError):
    def __init__(self, conflicts: list[dict[str, object]]) -> None:
        self.conflicts = conflicts
        super().__init__("任务目标与结构化条件存在明确冲突。")


def resolve_goal(goal: str, conditions: Conditions, consistency: GoalConsistency) -> str:
    replacements = {
        "people": str(conditions["people"]),
        "budget": str(conditions["budget"]),
    }
    resolved = goal
    for conflict in sorted(consistency.conflicts, key=lambda item: str(item["fragment"]), reverse=True):
        field = str(conflict["field"])
        fragment = str(conflict["fragment"])
        replacement = replacements.get(field)
        if replacement is not None:
            resolved = resolved.replace(
                fragment,
                re.sub(r"\d+(?:\.\d+)?", replacement, fragment, count=1),
                1,
            )
    return resolved


_PEOPLE = re.compile(r"(?<!\d)(\d{1,6})\s*(?:人|位|名(?:学生)?|学生)")
_BUDGET = re.compile(
    r"(?:总预算|预算|不超过|最多|限额)\s*[为是:：不超过最多限额]*\s*[¥￥]?(\d+(?:\.\d+)?)"
)


def check_goal_consistency(goal: str, conditions: Conditions) -> GoalConsistency:
    conflicts: list[dict[str, object]] = []
    uncertain: list[dict[str, object]] = []
    extracted: dict[str, tuple[object, str]] = {}
    people = _PEOPLE.search(goal)
    budget = _BUDGET.search(goal)
    if people:
        extracted["people"] = (int(people.group(1)), people.group(0))
    if budget:
        extracted["budget"] = (float(budget.group(1)), budget.group(0))
    for field in ("people", "budget"):
        if field not in conditions:
            if field not in extracted:
                uncertain.append({"field": field, "reason": "目标或条件缺失"})
            continue
        if field not in extracted:
            uncertain.append(
                {"field": field, "condition_value": conditions[field], "reason": "目标未明确表达"}
            )
            continue
        goal_value, fragment = extracted[field]
        condition_value = conditions[field]
        if float(goal_value) != float(condition_value):
            conflicts.append(
                {
                    "field": field,
                    "goal_value": goal_value,
                    "condition_value": condition_value,
                    "fragment": fragment,
                }
            )
    return GoalConsistency(conflicts=conflicts, uncertain=uncertain)