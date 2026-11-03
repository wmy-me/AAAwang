"""Request and response schemas for durable task runs."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr

RunStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
RunEventType = Literal[
    "run.queued",
    "run.running",
    "run.cancel_requested",
    "run.completed",
    "run.failed",
    "run.cancelled",
]


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    idempotency_key: StrictStr = Field(min_length=1, max_length=128)


class RunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    owner_id: uuid.UUID
    task_revision_id: uuid.UUID
    revision: int
    conditions: dict[str, object]
    idempotency_key: str
    status: RunStatus
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    attempt: int
    cancel_requested: bool
    diagnostic: dict[str, object] | None
    error_summary: str | None


class RunList(BaseModel):
    items: list[RunResponse]
    offset: int
    limit: int


class RunEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    sequence: int
    event_type: RunEventType
    occurred_at: datetime
    payload: dict[str, object]


class RunEventList(BaseModel):
    items: list[RunEventResponse]
    after: int
    limit: int
    next_after: int


class RunConflictDetail(BaseModel):
    message: str
    current_revision: int


class RunConflictResponse(BaseModel):
    detail: RunConflictDetail