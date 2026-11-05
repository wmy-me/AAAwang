"""Request and response schemas for durable task runs."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr

RunStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
RunExecutionType = Literal[
    "diagnostic",
    "capability_decision",
    "direct_answer",
    "shopping_research",
    "shopping_agent",
    "map_places",
    "weather",
    "capability_router",
    "web_search",
]
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
    execution_type: RunExecutionType = "diagnostic"


class RunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    task_id: uuid.UUID | None
    owner_id: uuid.UUID
    task_revision_id: uuid.UUID | None
    revision: int
    goal: str
    conditions: dict[str, object]
    idempotency_key: str
    execution_type: RunExecutionType
    capability_ids: list[str] | None
    decision: dict[str, object] | None
    budget: dict[str, object] | None
    status: RunStatus
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    attempt: int
    cancel_requested: bool
    diagnostic: dict[str, object] | None
    error_summary: str | None


class ShoppingRunResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_id: uuid.UUID
    answer: str
    source: dict[str, object]
    execution_version: str
    created_at: datetime
    decision_type: Literal[
        "direct_answer", "clarification", "delegated_discovery"
    ] = "delegated_discovery"
    delegated: bool = False
    mcp_call_count: int = 0


class ShoppingCandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: str
    name: str
    unit_price: Decimal
    currency: str
    unit: str
    distributable_units: int
    source_type: str
    source_service: str
    simulated: bool
    availability: str
    quoted_at: datetime | None
    queried_at: datetime


class ShoppingPlanItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    candidate_id: uuid.UUID
    package_quantity: int
    covered_people: int
    subtotal: Decimal
    candidate: ShoppingCandidateResponse


class ShoppingPlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_id: uuid.UUID
    revision: int
    status: str
    people: int
    covered_people: int
    budget: Decimal
    total: Decimal
    remaining: Decimal
    currency: str
    unknown_fees: bool
    note: str
    created_at: datetime
    items: list[ShoppingPlanItemResponse]


class ShoppingArtifactsResponse(BaseModel):
    candidates: list[ShoppingCandidateResponse]
    plan: ShoppingPlanResponse | None


class MapPlaceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    revision: int
    name: str
    address: str | None
    location: str | None
    phone: str | None
    url: str | None
    query: str
    city: str
    source_service: str
    source_tool: str
    observed_at: datetime


class WeatherForecastResponse(BaseModel):
    date: str | None
    week: str | None
    day_weather: str | None
    night_weather: str | None
    day_temperature: str | None
    night_temperature: str | None
    day_wind: str | None
    night_wind: str | None
    day_wind_power: str | None
    night_wind_power: str | None


class WeatherSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_id: uuid.UUID
    revision: int
    city: str
    source_service: str
    source_tool: str
    queried_at: datetime
    forecasts: list[WeatherForecastResponse]


class WebSearchResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    revision: int
    title: str
    url: str
    summary: str | None
    published_at: str | None
    source_service: str
    source_tool: str
    observed_at: datetime


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