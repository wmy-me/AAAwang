"""Persistent account, conversation, task, and run models."""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    desc,
    func,
    text,
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
        Index("ix_messages_task_created_id", "task_id", "created_at", "id"),
        Index(
            "uq_messages_assistant_run_id",
            "run_id",
            unique=True,
            postgresql_where=text("role = 'assistant'"),
            sqlite_where=text("role = 'assistant'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    client_message_id: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16), default="user")
    content: Mapped[str] = mapped_column(Text)
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
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
    goal: Mapped[str] = mapped_column(String(500))
    goal_conflicts: Mapped[list[dict[str, object]] | None] = mapped_column(JSON)
    goal_resolution: Mapped[str | None] = mapped_column(String(32))
    goal_legacy: Mapped[bool] = mapped_column(Boolean, default=False)
    conditions: Mapped[dict[str, object]] = mapped_column(JSON)
    change_note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    task: Mapped[Task] = relationship(back_populates="revisions")


class DynamicFormProposal(Base):
    __tablename__ = "dynamic_form_proposals"
    __table_args__ = (
        UniqueConstraint(
            "task_id", "task_revision_id", name="uq_form_proposals_task_revision"
        ),
        UniqueConstraint(
            "task_id", "client_request_id", name="uq_form_proposals_task_request"
        ),
        Index("ix_form_proposals_task_created", "task_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    task_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("task_revisions.id", ondelete="CASCADE")
    )
    revision: Mapped[int]
    schema: Mapped[list[dict[str, object]]] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(32), default="server_registered")
    status: Mapped[str] = mapped_column(String(16), default="pending")
    confirmed_values: Mapped[dict[str, object] | None] = mapped_column(JSON)
    client_request_id: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    task: Mapped[Task] = relationship()
    task_revision: Mapped[TaskRevision] = relationship()


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint(
            "task_id", "idempotency_key", name="uq_runs_task_idempotency_key"
        ),
        UniqueConstraint(
            "conversation_id", "idempotency_key", name="uq_runs_conversation_idempotency_key"
        ),
        Index("ix_runs_task_created_id", "task_id", desc("created_at"), desc("id")),
        Index("ix_runs_claimable", "status", "lease_until", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    task_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("task_revisions.id", ondelete="CASCADE")
    )
    input_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), index=True
    )
    revision: Mapped[int]
    goal: Mapped[str] = mapped_column(String(500))
    conditions: Mapped[dict[str, object]] = mapped_column(JSON)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    execution_type: Mapped[str] = mapped_column(String(32), default="diagnostic")
    capability_ids: Mapped[list[str] | None] = mapped_column(JSON)
    decision: Mapped[dict[str, object] | None] = mapped_column(JSON)
    budget: Mapped[dict[str, object] | None] = mapped_column(JSON)
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
    conversation: Mapped[Conversation] = relationship()
    task: Mapped[Task | None] = relationship(back_populates="runs")
    task_revision: Mapped[TaskRevision | None] = relationship()
    owner: Mapped[User] = relationship(back_populates="runs")
    shopping_result: Mapped["ShoppingRunResult | None"] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )
    events: Mapped[list["RunEvent"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )
    shopping_candidates: Mapped[list["ShoppingCandidate"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )
    shopping_plan: Mapped["ShoppingPlan | None"] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )
    map_places: Mapped[list["MapPlace"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )
    weather_snapshot: Mapped["WeatherSnapshot | None"] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )
    web_search_results: Mapped[list["WebSearchResult"]] = relationship(
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
    decision_type: Mapped[str] = mapped_column(String(32), default="delegated_discovery")
    delegated: Mapped[bool] = mapped_column(Boolean, default=False)
    mcp_call_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    run: Mapped[Run] = relationship(back_populates="shopping_result")


class MapPlace(Base):
    __tablename__ = "map_places"
    __table_args__ = (
        UniqueConstraint("run_id", "place_key", name="uq_map_places_run_place"),
        Index("ix_map_places_task_revision", "task_id", "revision"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    task_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("task_revisions.id", ondelete="CASCADE")
    )
    revision: Mapped[int] = mapped_column(Integer)
    place_key: Mapped[str] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(String(240))
    address: Mapped[str | None] = mapped_column(String(240))
    location: Mapped[str | None] = mapped_column(String(240))
    phone: Mapped[str | None] = mapped_column(String(80))
    url: Mapped[str | None] = mapped_column(String(240))
    query: Mapped[str] = mapped_column(String(120))
    city: Mapped[str] = mapped_column(String(120))
    source_service: Mapped[str] = mapped_column(String(64))
    source_tool: Mapped[str] = mapped_column(String(128))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    run: Mapped[Run] = relationship(back_populates="map_places")


class WeatherSnapshot(Base):
    __tablename__ = "weather_snapshots"
    __table_args__ = (Index("ix_weather_snapshots_task_revision", "task_id", "revision"),)

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    task_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("task_revisions.id", ondelete="CASCADE")
    )
    revision: Mapped[int] = mapped_column(Integer)
    city: Mapped[str] = mapped_column(String(120))
    source_service: Mapped[str] = mapped_column(String(64))
    source_tool: Mapped[str] = mapped_column(String(128))
    queried_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    forecasts: Mapped[list[dict[str, object]]] = mapped_column(JSON)
    run: Mapped[Run] = relationship(back_populates="weather_snapshot")


class WebSearchResult(Base):
    __tablename__ = "web_search_results"
    __table_args__ = (
        UniqueConstraint("run_id", "result_key", name="uq_web_search_run_result"),
        Index("ix_web_search_task_revision", "task_id", "revision"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    task_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("task_revisions.id", ondelete="CASCADE")
    )
    revision: Mapped[int] = mapped_column(Integer)
    result_key: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(String(2000))
    summary: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[str | None] = mapped_column(String(80))
    source_service: Mapped[str] = mapped_column(String(64))
    source_tool: Mapped[str] = mapped_column(String(128))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    run: Mapped[Run] = relationship(back_populates="web_search_results")


class ShoppingCandidate(Base):
    __tablename__ = "shopping_candidates"
    __table_args__ = (
        UniqueConstraint("run_id", "product_id", name="uq_candidates_run_product"),
        Index("ix_candidates_task_revision", "task_id", "revision"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    task_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("task_revisions.id", ondelete="CASCADE")
    )
    revision: Mapped[int] = mapped_column(Integer)
    product_id: Mapped[str] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(String(240))
    unit_price: Mapped[object] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    unit: Mapped[str] = mapped_column(String(120))
    distributable_units: Mapped[int] = mapped_column(Integer)
    source_type: Mapped[str] = mapped_column(String(32))
    source_service: Mapped[str] = mapped_column(String(64))
    simulated: Mapped[bool] = mapped_column(Boolean)
    availability: Mapped[str] = mapped_column(String(120))
    quoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    queried_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    run: Mapped[Run] = relationship(back_populates="shopping_candidates")


class ShoppingPlan(Base):
    __tablename__ = "shopping_plans"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    task_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("task_revisions.id", ondelete="CASCADE")
    )
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32))
    people: Mapped[int] = mapped_column(Integer)
    covered_people: Mapped[int] = mapped_column(Integer)
    budget: Mapped[object] = mapped_column(Numeric(12, 2))
    total: Mapped[object] = mapped_column(Numeric(12, 2))
    remaining: Mapped[object] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    unknown_fees: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    run: Mapped[Run] = relationship(back_populates="shopping_plan")
    items: Mapped[list["ShoppingPlanItem"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", passive_deletes=True
    )


class ShoppingPlanItem(Base):
    __tablename__ = "shopping_plan_items"
    __table_args__ = (
        UniqueConstraint("run_id", "candidate_id", name="uq_plan_items_candidate"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shopping_plans.run_id", ondelete="CASCADE"), index=True
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shopping_candidates.id", ondelete="RESTRICT")
    )
    package_quantity: Mapped[int] = mapped_column(Integer)
    covered_people: Mapped[int] = mapped_column(Integer)
    subtotal: Mapped[object] = mapped_column(Numeric(12, 2))
    plan: Mapped[ShoppingPlan] = relationship(back_populates="items")
    candidate: Mapped[ShoppingCandidate] = relationship()


class ShoppingPlanAdjustment(Base):
    __tablename__ = "shopping_plan_adjustments"
    __table_args__ = (
        UniqueConstraint("task_id", "version", name="uq_plan_adjustments_task_version"),
        UniqueConstraint(
            "task_id", "client_request_id", name="uq_plan_adjustments_task_request"
        ),
        Index("ix_plan_adjustments_task_current", "task_id", "is_current"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    task_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("task_revisions.id", ondelete="CASCADE")
    )
    base_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="RESTRICT")
    )
    version: Mapped[int] = mapped_column(Integer)
    client_request_id: Mapped[str] = mapped_column(String(128))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(32), default="manual_adjustment")
    status: Mapped[str] = mapped_column(String(32), default="valid")
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    people: Mapped[int] = mapped_column(Integer)
    covered_people: Mapped[int] = mapped_column(Integer)
    budget: Mapped[object] = mapped_column(Numeric(12, 2))
    total: Mapped[object] = mapped_column(Numeric(12, 2))
    remaining: Mapped[object] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    unknown_fees: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    items: Mapped[list["ShoppingPlanAdjustmentItem"]] = relationship(
        back_populates="adjustment", cascade="all, delete-orphan", passive_deletes=True
    )


class ShoppingPlanAdjustmentItem(Base):
    __tablename__ = "shopping_plan_adjustment_items"
    __table_args__ = (
        UniqueConstraint(
            "adjustment_id", "candidate_id", name="uq_plan_adjustment_items_candidate"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    adjustment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shopping_plan_adjustments.id", ondelete="CASCADE"), index=True
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shopping_candidates.id", ondelete="RESTRICT")
    )
    package_quantity: Mapped[int] = mapped_column(Integer)
    covered_people: Mapped[int] = mapped_column(Integer)
    subtotal: Mapped[object] = mapped_column(Numeric(12, 2))
    adjustment: Mapped[ShoppingPlanAdjustment] = relationship(back_populates="items")
    candidate: Mapped[ShoppingCandidate] = relationship()
