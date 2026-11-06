"""Owner-scoped, bounded short-term conversation context.

The builder deliberately returns data, rather than provider message objects: callers
choose the smallest view appropriate to their role.  Database messages remain the
source of truth and are never rewritten or summarized here.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
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
    """Build recent complete conversational turns after owner verification.

    A character estimate is intentionally conservative (four characters per token
    is not assumed); long messages consume their complete turn or are omitted.
    Tool protocol messages are not persisted by this application today.  Should
    they be added, their run group must be retained or removed as a whole.
    """

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
        owned = db.scalar(select(Conversation.id).where(Conversation.id == conversation_id, Conversation.owner_id == owner_id))
        if owned is None:
            raise LookupError("conversation is not owned")
        rows = list(db.scalars(
            select(Message)
            .outerjoin(Run, Message.run_id == Run.id)
            .where(Message.conversation_id == conversation_id)
            # Assistant output from a failed/cancelled run is never context.
            .where((Message.role != "assistant") | (Run.status == "completed"))
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(self.max_messages * 4 + 8)
        ))
        if before_message_id is not None:
            index = next((i for i, row in enumerate(rows) if row.id == before_message_id), None)
            if index is not None:
                rows = rows[index + 1 :]
        rows.reverse()
        selected: list[ContextMessage] = []
        chars = 0
        for row in reversed(rows):
            size = len(row.content)
            if len(selected) >= self.max_messages or chars + size > self.max_characters:
                continue
            selected.append(ContextMessage(row.role, row.content))
            chars += size
        selected.reverse()
        truncated = len(selected) < len(rows)
        return ConversationContext(tuple(selected), truncated, chars)

    def task_snapshot(self, db: Session, task: Task) -> dict[str, object]:
        revision = db.scalar(select(TaskRevision).where(TaskRevision.task_id == task.id, TaskRevision.revision == task.current_revision))
        return {"id": str(task.id), "goal": task.goal, "revision": task.current_revision,
                "domain": task.domain, "conditions": dict(revision.conditions) if revision else {}}
