"""Owner-scoped private conversation persistence operations."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from life_agent.db.models import Conversation, Message


class ConversationNotFoundError(LookupError):
    """Raised when an owner-scoped conversation cannot be found."""


class ClientMessageConflictError(ValueError):
    """Raised when an idempotency key is reused with different content."""


@dataclass(frozen=True)
class AppendedMessage:
    message: Message
    created: bool


def create_conversation(
    db: Session, owner_id: uuid.UUID, title: str | None
) -> Conversation:
    conversation = Conversation(owner_id=owner_id, title=title)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def list_conversations(
    db: Session, owner_id: uuid.UUID, offset: int, limit: int
) -> list[Conversation]:
    return list(
        db.scalars(
            select(Conversation)
            .where(Conversation.owner_id == owner_id)
            .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )


def get_conversation(
    db: Session, owner_id: uuid.UUID, conversation_id: uuid.UUID
) -> Conversation:
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.owner_id == owner_id,
        )
    )
    if conversation is None:
        raise ConversationNotFoundError
    return conversation


def update_conversation_title(
    db: Session,
    owner_id: uuid.UUID,
    conversation_id: uuid.UUID,
    title: str | None,
) -> Conversation:
    conversation = get_conversation(db, owner_id, conversation_id)
    conversation.title = title
    conversation.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(conversation)
    return conversation


def append_message(
    db: Session,
    owner_id: uuid.UUID,
    conversation_id: uuid.UUID,
    client_message_id: str,
    content: str,
) -> AppendedMessage:
    conversation = get_conversation(db, owner_id, conversation_id)
    existing = _get_message_by_client_id(db, conversation_id, client_message_id)
    if existing is not None:
        return _resolve_idempotent_message(existing, content)

    message = Message(
        conversation_id=conversation_id,
        client_message_id=client_message_id,
        role="user",
        content=content,
        created_at=datetime.now(UTC),
    )
    db.add(message)
    conversation.updated_at = datetime.now(UTC)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = _get_message_by_client_id(db, conversation_id, client_message_id)
        if existing is None:
            raise
        return _resolve_idempotent_message(existing, content)
    db.refresh(message)
    return AppendedMessage(message=message, created=True)


def list_messages(
    db: Session,
    owner_id: uuid.UUID,
    conversation_id: uuid.UUID,
    offset: int,
    limit: int,
) -> list[Message]:
    get_conversation(db, owner_id, conversation_id)
    return list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at, Message.id)
            .offset(offset)
            .limit(limit)
        )
    )


def _get_message_by_client_id(
    db: Session, conversation_id: uuid.UUID, client_message_id: str
) -> Message | None:
    return db.scalar(
        select(Message).where(
            Message.conversation_id == conversation_id,
            Message.client_message_id == client_message_id,
        )
    )


def _resolve_idempotent_message(message: Message, content: str) -> AppendedMessage:
    if message.content != content:
        raise ClientMessageConflictError
    return AppendedMessage(message=message, created=False)