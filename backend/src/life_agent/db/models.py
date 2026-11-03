"""Persistent account, conversation, task, and run models."""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    desc,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from life_agent.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    sessions: Mapped[list["LoginSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan", passive_deletes=True
    )
    runs: Mapped[list["Run"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan", passive_deletes=True
    )


class LoginSession(Base):
    __tablename__ = "login_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    user: Mapped[User] = relationship(back_populates="sessions")


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index(
            "ix_conversations_owner_updated_id",
            "owner_id",
            desc("updated_at"),
            desc("id"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    title: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    owner: Mapped[User] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", passive_deletes=True
    )
    tasks: Mapped[list["Task"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", passive_deletes=True
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "client_message_id",
            name="uq_messages_conversation_client_message_id",
        ),
        Index(
            "ix_messages_conversation_created_id",
            "conversation_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    client_message_id: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16), default="user")
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index(
            "ix_tasks_conversation_updated_id",
            "conversation_id",
            desc("updated_at"),
            desc("id"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    domain: Mapped[str] = mapped_column(String(24))
    goal: Mapped[str] = mapped_column(String(500))
    current_revision: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    conversation: Mapped[Conversation] = relationship(back_populates="tasks")
    revisions: Mapped[list["TaskRevision"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", passive_deletes=True
    )
    runs: Mapped[list["Run"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", passive_deletes=True
    )


class TaskRevision(Base):
    __tablename__ = "task_revisions"
    __table_args__ = (
        UniqueConstraint("task_id", "revision", name="uq_task_revisions_version"),
        Index("ix_task_revisions_task_revision", "task_id", "revision"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE")
    )
    revision: Mapped[int]
    conditions: Mapped[dict[str, object]] = mapped_column(JSON)
    change_note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    task: Mapped[Task] = relationship(back_populates="revisions")


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint(
            "task_id", "idempotency_key", name="uq_runs_task_idempotency_key"
        ),
        Index("ix_runs_task_created_id", "task_id", desc("created_at"), desc("id")),
        Index("ix_runs_claimable", "status", "lease_until", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    task_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("task_revisions.id", ondelete="CASCADE")
    )
    revision: Mapped[int]
    conditions: Mapped[dict[str, object]] = mapped_column(JSON)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    execution_type: Mapped[str] = mapped_column(String(32), default="diagnostic")
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(String(128))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt: Mapped[int] = mapped_column(default=0)
    fencing_token: Mapped[int] = mapped_column(default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    diagnostic: Mapped[dict[str, object] | None] = mapped_column(JSON)
    error_summary: Mapped[str | None] = mapped_column(String(500))
    task: Mapped[Task] = relationship(back_populates="runs")
    task_revision: Mapped[TaskRevision] = relationship()
    owner: Mapped[User] = relationship(back_populates="runs")
    shopping_result: Mapped["ShoppingRunResult | None"] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )
    events: Mapped[list["RunEvent"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )


class RunEvent(Base):
    __tablename__ = "run_events"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_run_events_run_sequence"),
        Index("ix_run_events_run_sequence", "run_id", "sequence"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int]
    event_type: Mapped[str] = mapped_column(String(32))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    payload: Mapped[dict[str, object]] = mapped_column(JSON)
    run: Mapped[Run] = relationship(back_populates="events")


class ShoppingRunResult(Base):
    __tablename__ = "shopping_run_results"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    answer: Mapped[str] = mapped_column(Text)
    source: Mapped[dict[str, object]] = mapped_column(JSON)
    execution_version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    run: Mapped[Run] = relationship(back_populates="shopping_result")