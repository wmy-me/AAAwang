"""Public request and response schemas for private conversations."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConversationCreate(StrictRequest):
    title: str | None = Field(default=None, max_length=120)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("标题不能只包含空白字符。")
        return normalized


class ConversationUpdate(StrictRequest):
    title: str | None = Field(max_length=120)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        return ConversationCreate.normalize_title(value)


class MessageCreate(StrictRequest):
    client_message_id: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=8000)

    @field_validator("client_message_id", "content")
    @classmethod
    def reject_blank_value(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("字段不能只包含空白字符。")
        return value


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    created_at: datetime
    updated_at: datetime


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    client_message_id: str
    role: str
    content: str
    created_at: datetime


class ConversationList(BaseModel):
    items: list[ConversationResponse]
    offset: int
    limit: int


class MessageList(BaseModel):
    items: list[MessageResponse]
    offset: int
    limit: int