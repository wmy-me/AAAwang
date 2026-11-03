"""Persist immutable goal snapshots for task revisions and runs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261103_0013"
down_revision: str | None = "20261103_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("task_revisions", sa.Column("goal", sa.String(500), nullable=True))
    op.add_column("task_revisions", sa.Column("goal_conflicts", sa.JSON(), nullable=True))
    op.add_column("task_revisions", sa.Column("goal_resolution", sa.String(32), nullable=True))
    op.add_column("task_revisions", sa.Column("goal_legacy", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute(
        sa.text(
            "UPDATE task_revisions SET goal = tasks.goal, goal_legacy = TRUE "
            "FROM tasks WHERE task_revisions.task_id = tasks.id"
        )
    )
    op.alter_column("task_revisions", "goal", nullable=False)
    op.add_column("runs", sa.Column("goal", sa.String(500), nullable=True))
    op.execute(
        sa.text(
            "UPDATE runs SET goal = task_revisions.goal "
            "FROM task_revisions WHERE runs.task_revision_id = task_revisions.id"
        )
    )
    op.alter_column("runs", "goal", nullable=False)


def downgrade() -> None:
    op.drop_column("runs", "goal")
    op.drop_column("task_revisions", "goal_legacy")
    op.drop_column("task_revisions", "goal_resolution")
    op.drop_column("task_revisions", "goal_conflicts")
    op.drop_column("task_revisions", "goal")