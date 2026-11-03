"""Request and response schemas for private versioned tasks."""

import json
import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_validator,
)

TaskDomain = Literal["shopping", "travel"]
ConditionValue = StrictStr | StrictInt | StrictFloat
Conditions = dict[str, ConditionValue]

ALLOWED_CONDITIONS: dict[str, dict[str, type[object]]] = {
    "shopping": {
        "budget": float,
        "people": int,
        "item": str,
        "quantity": int,
    },
    "travel": {
        "budget": float,
        "people": int,
        "destination": str,
        "start_date": str,
        "end_date": str,
    },
}
MAX_CONDITIONS_BYTES = 16 * 1024


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


def validate_conditions(domain: str, conditions: Conditions) -> Conditions:
    encoded = json.dumps(conditions, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_CONDITIONS_BYTES:
        raise ValueError("条件快照不能超过 16 KiB。")
    allowed = ALLOWED_CONDITIONS[domain]
    unknown = conditions.keys() - allowed.keys()
    if unknown:
        raise ValueError(f"条件包含未知字段: {', '.join(sorted(unknown))}。")
    for name, value in conditions.items():
        expected = allowed[name]
        if expected is float:
            if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
                raise ValueError(f"{name} 必须是正数。")
        elif expected is int:
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} 必须是正整数。")
        elif not isinstance(value, str) or not value.strip() or len(value) > 200:
            raise ValueError(f"{name} 必须是 1–200 字符的非空字符串。")
    if domain == "travel":
        parsed_dates: dict[str, date] = {}
        for name in ("start_date", "end_date"):
            if name in conditions:
                try:
                    parsed_dates[name] = date.fromisoformat(str(conditions[name]))
                except ValueError as exc:
                    raise ValueError(f"{name} 必须是 YYYY-MM-DD 日期。") from exc
        if (
            parsed_dates.get("start_date")
            and parsed_dates.get("end_date")
            and parsed_dates["end_date"] < parsed_dates["start_date"]
        ):
            raise ValueError("end_date 不能早于 start_date。")
    return conditions


class TaskCreate(StrictRequest):
    domain: TaskDomain
    goal: str = Field(min_length=1, max_length=500)
    conditions: Conditions = Field(default_factory=dict)
    change_note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_snapshot(self) -> "TaskCreate":
        self.goal = self.goal.strip()
        if not self.goal:
            raise ValueError("任务目标不能只包含空白字符。")
        if self.change_note is not None:
            self.change_note = self.change_note.strip() or None
        self.conditions = validate_conditions(self.domain, self.conditions)
        return self


class TaskRevisionCreate(StrictRequest):
    expected_revision: int = Field(ge=1)
    goal: str | None = Field(default=None, min_length=1, max_length=500)
    conditions: Conditions
    change_note: str | None = Field(default=None, max_length=500)
    confirm_goal_conflict: bool = False

    @model_validator(mode="after")
    def normalize_goal(self) -> "TaskRevisionCreate":
        if self.goal is not None:
            self.goal = self.goal.strip()
            if not self.goal:
                raise ValueError("任务目标不能只包含空白字符。")
        if self.change_note is not None:
            self.change_note = self.change_note.strip() or None
        return self


class TaskRevisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    revision: int
    goal: str
    goal_conflicts: list[dict[str, object]] | None
    goal_resolution: str | None
    goal_legacy: bool
    conditions: Conditions
    change_note: str | None
    created_at: datetime


class TaskResponse(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    domain: TaskDomain
    goal: str
    current_revision: int
    conditions: Conditions
    goal_conflicts: list[dict[str, object]] | None = None
    goal_resolution: str | None = None
    goal_legacy: bool = False
    created_at: datetime
    updated_at: datetime


class TaskList(BaseModel):
    items: list[TaskResponse]
    offset: int
    limit: int


class TaskRevisionList(BaseModel):
    items: list[TaskRevisionResponse]
    offset: int
    limit: int


class RevisionConflictDetail(BaseModel):
    message: str
    current_revision: int


class RevisionConflictResponse(BaseModel):
    detail: RevisionConflictDetail