"""Bind shopping chat messages to tasks and runs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261103_0009"
down_revision: str | None = "20261103_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("task_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column("run_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "runs",
        sa.Column("input_message_id", sa.Uuid(), nullable=True),
    )
    op.create_index("ix_messages_task_created_id", "messages", ["task_id", "created_at", "id"])
    op.create_index("ix_messages_task_id", "messages", ["task_id"])
    op.create_index("ix_messages_run_id", "messages", ["run_id"])
    op.create_index("ix_runs_input_message_id", "runs", ["input_message_id"])
    op.create_unique_constraint("uq_messages_run_id", "messages", ["run_id"])
    op.create_foreign_key(
        "fk_messages_task_id_tasks",
        "messages",
        "tasks",
        ["task_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_messages_run_id_runs",
        "messages",
        "runs",
        ["run_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_runs_input_message_id_messages",
        "runs",
        "messages",
        ["input_message_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_runs_input_message_id_messages", "runs", type_="foreignkey")
    op.drop_constraint("fk_messages_run_id_runs", "messages", type_="foreignkey")
    op.drop_constraint("fk_messages_task_id_tasks", "messages", type_="foreignkey")
    op.drop_constraint("uq_messages_run_id", "messages", type_="unique")
    op.drop_index("ix_runs_input_message_id", table_name="runs")
    op.drop_index("ix_messages_run_id", table_name="messages")
    op.drop_index("ix_messages_task_id", table_name="messages")
    op.drop_index("ix_messages_task_created_id", table_name="messages")
    op.drop_column("runs", "input_message_id")
    op.drop_column("messages", "run_id")
    op.drop_column("messages", "task_id")
