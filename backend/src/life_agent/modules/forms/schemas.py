"""Contracts for bounded dynamic task forms."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr

from life_agent.modules.conversations.schemas import MessageResponse
from life_agent.modules.runs.schemas import RunResponse
from life_agent.modules.tasks.schemas import TaskResponse

FormControl = Literal[
    "short_text", "number", "money", "date", "single_select", "multi_select", "location"
]
FormValue = StrictStr | StrictInt | StrictFloat | list[StrictStr]


class FormField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: StrictStr = Field(min_length=1, max_length=32, pattern=r"^[a-z][a-z0-9_]*$")
    control: FormControl
    label: StrictStr = Field(min_length=1, max_length=80)
    reason: StrictStr = Field(min_length=1, max_length=240)
    required: bool = False
    unit: StrictStr | None = Field(default=None, max_length=24)
    options: list[StrictStr] | None = None
    min_value: StrictFloat | StrictInt | None = None
    max_value: StrictFloat | StrictInt | None = None


class DynamicFormProposalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    task_revision_id: uuid.UUID
    revision: int
    fields: list[FormField] = Field(validation_alias="schema", serialization_alias="schema")
    source: str
    status: Literal["pending", "confirmed"]
    confirmed_values: dict[str, FormValue] | None
    created_at: datetime
    confirmed_at: datetime | None


class FormSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: uuid.UUID
    expected_revision: int = Field(ge=1)
    client_request_id: StrictStr = Field(min_length=1, max_length=128)
    values: dict[str, FormValue]


class FormSubmitResponse(BaseModel):
    message: MessageResponse
    run: RunResponse
    task: TaskResponse