"""Owner-scoped, bounded short-term conversation context.

The builder deliberately returns data, rather than provider message objects: callers
choose the smallest view appropriate to their role.  Database messages remain the
source of truth and are never rewritten or summarized here.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from life_agent.db.models import Conversation, Message, Run, Task, TaskRevision


@dataclass(frozen=True)
class ContextMessage:
    role: str
    content: str


@dataclass(frozen=True)
class ConversationContext:
    messages: tuple[ContextMessage, ...]
    truncated: bool
    estimated_characters: int

    def as_prompt(self) -> str:
        text = "\n".join(f"{m.role}: {m.content}" for m in self.messages)
        boundary = "\n[更早对话未纳入；不要把此视为完整历史。]" if self.truncated else ""
        return text + boundary if text else "（无历史）"


class ContextBuilder:
    """Build a continuous suffix of complete prior turns after owner verification."""

    def __init__(self, *, max_messages: int, max_characters: int) -> None:
        self.max_messages = max_messages
        self.max_characters = max_characters

    def build(
        self,
        db: Session,
        owner_id: uuid.UUID,
        conversation_id: uuid.UUID,
        *,
        before_message_id: uuid.UUID | None = None,
    ) -> ConversationContext:
        if db.scalar(select(Conversation.id).where(Conversation.id == conversation_id, Conversation.owner_id == owner_id)) is None:
            raise LookupError("conversation is not owned")
        cursor: Message | None = None
        if before_message_id is not None:
            cursor = db.scalar(select(Message).where(
                Message.id == before_message_id,
                Message.conversation_id == conversation_id,
            ))
            if cursor is None:
                # Fail closed: a delayed Worker must not read later messages.
                return ConversationContext((), True, 0)
        query = (
            select(Message)
            .outerjoin(Run, Message.run_id == Run.id)
            .where(Message.conversation_id == conversation_id)
            .where((Message.role != "assistant") | (Run.status == "completed"))
        )
        if cursor is not None:
            query = query.where(or_(
                Message.created_at < cursor.created_at,
                and_(Message.created_at == cursor.created_at, Message.id < cursor.id),
            ))
        rows = list(db.scalars(query.order_by(Message.created_at, Message.id)))
        turns = self._turns(rows)
        chosen: list[list[Message]] = []
        count = chars = 0
        truncated = False
        for turn in reversed(turns):
            turn_count = len(turn)
            turn_chars = sum(len(row.content) for row in turn)
            if count + turn_count > self.max_messages or chars + turn_chars > self.max_characters:
                # Keep a continuous suffix; never skip an overlong recent turn
                # just to introduce older, unrelated context.
                truncated = True
                break
            chosen.append(turn)
            count += turn_count
            chars += turn_chars
        chosen.reverse()
        selected = tuple(ContextMessage(row.role, row.content) for turn in chosen for row in turn)
        return ConversationContext(selected, truncated or len(selected) < len(rows), chars)

    @staticmethod
    def _turns(rows: list[Message]) -> list[list[Message]]:
        turns: list[list[Message]] = []
        by_run: dict[uuid.UUID, list[Message]] = {}
        for row in rows:
            if row.run_id is not None and row.run_id in by_run:
                by_run[row.run_id].append(row)
            elif row.run_id is not None:
                group = [row]
                by_run[row.run_id] = group
                turns.append(group)
            else:
                turns.append([row])
        return turns

    def task_snapshot(self, db: Session, task: Task) -> dict[str, object]:
        revision = db.scalar(select(TaskRevision).where(TaskRevision.task_id == task.id, TaskRevision.revision == task.current_revision))
        return {"id": str(task.id), "goal": task.goal, "revision": task.current_revision,
                "domain": task.domain, "conditions": dict(revision.conditions) if revision else {}}
