"""Allow conversation-only direct-answer runs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261105_0020"
down_revision: str | None = "20261105_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_runs_conversation_id",
        "runs",
        "conversations",
        ["conversation_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_runs_conversation_id", "runs", ["conversation_id"])
    op.create_unique_constraint(
        "uq_runs_conversation_idempotency_key",
        "runs",
        ["conversation_id", "idempotency_key"],
    )
    op.alter_column("runs", "task_id", existing_type=sa.Uuid(), nullable=True)
    op.alter_column(
        "runs", "task_revision_id", existing_type=sa.Uuid(), nullable=True
    )
    op.execute(
        sa.text(
            "UPDATE runs SET conversation_id = conversations.id "
            "FROM tasks JOIN conversations ON conversations.id = tasks.conversation_id "
            "WHERE runs.task_id = tasks.id"
        )
    )
    op.alter_column("runs", "conversation_id", nullable=False)


def downgrade() -> None:
    op.drop_constraint("uq_runs_conversation_idempotency_key", "runs", type_="unique")
    op.drop_index("ix_runs_conversation_id", table_name="runs")
    op.drop_constraint("fk_runs_conversation_id", "runs", type_="foreignkey")
    op.drop_column("runs", "conversation_id")
    op.alter_column("runs", "task_revision_id", existing_type=sa.Uuid(), nullable=False)
    op.alter_column("runs", "task_id", existing_type=sa.Uuid(), nullable=False)
