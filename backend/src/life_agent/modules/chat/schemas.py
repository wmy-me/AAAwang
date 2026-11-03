"""Request and response schemas for selected-task chat turns."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from life_agent.modules.conversations.schemas import MessageResponse
from life_agent.modules.runs.schemas import RunResponse
from life_agent.modules.tasks.schemas import TaskResponse


class TaskChatTurnCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_turn_id: StrictStr = Field(min_length=1, max_length=128)
    content: StrictStr = Field(min_length=1, max_length=8000)
    task_id: uuid.UUID
    expected_revision: int = Field(ge=1)


class TaskChatTurnResponse(BaseModel):
    message: MessageResponse
    run: RunResponse
    task: TaskResponse
    assistant_message: MessageResponse | None = None


class TaskChatMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    client_message_id: str
    role: str
    content: str
    task_id: uuid.UUID | None
    run_id: uuid.UUID | None
    created_at: datetime
