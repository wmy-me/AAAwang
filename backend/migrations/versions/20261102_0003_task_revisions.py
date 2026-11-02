"""Create private tasks and immutable condition revisions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261102_0003"
down_revision: str | None = "20261102_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("domain", sa.String(length=24), nullable=False),
        sa.Column("goal", sa.String(length=500), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_tasks_conversation_updated_id",
        "tasks",
        ["conversation_id", sa.text("updated_at DESC"), sa.text("id DESC")],
    )
    op.create_table(
        "task_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("conditions", sa.JSON(), nullable=False),
        sa.Column("change_note", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "revision", name="uq_task_revisions_version"),
    )
    op.create_index(
        "ix_task_revisions_task_revision",
        "task_revisions",
        ["task_id", "revision"],
    )


def downgrade() -> None:
    op.drop_index("ix_task_revisions_task_revision", table_name="task_revisions")
    op.drop_table("task_revisions")
    op.drop_index("ix_tasks_conversation_updated_id", table_name="tasks")
    op.drop_table("tasks")