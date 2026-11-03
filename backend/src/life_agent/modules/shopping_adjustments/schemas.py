"""Request and response schemas for immutable shopping-plan adjustments."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from life_agent.modules.runs.schemas import ShoppingCandidateResponse


class ShoppingAdjustmentItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: uuid.UUID
    package_quantity: int = Field(ge=1, le=10_000)


class ShoppingAdjustmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_run_id: uuid.UUID
    expected_revision: int = Field(ge=1)
    expected_adjustment_version: int = Field(ge=0)
    client_request_id: str = Field(min_length=1, max_length=128)
    items: list[ShoppingAdjustmentItemCreate] = Field(min_length=1, max_length=100)


class ShoppingAdjustmentItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    candidate_id: uuid.UUID
    package_quantity: int
    covered_people: int
    subtotal: Decimal
    candidate: ShoppingCandidateResponse


class ShoppingAdjustmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    task_id: uuid.UUID
    task_revision_id: uuid.UUID
    base_run_id: uuid.UUID
    version: int
    client_request_id: str
    source: str
    status: str
    is_current: bool
    people: int
    covered_people: int
    budget: Decimal
    total: Decimal
    remaining: Decimal
    currency: str
    unknown_fees: bool
    note: str
    created_at: datetime
    items: list[ShoppingAdjustmentItemResponse]


class ShoppingAdjustmentList(BaseModel):
    items: list[ShoppingAdjustmentResponse]
    current_version: int
