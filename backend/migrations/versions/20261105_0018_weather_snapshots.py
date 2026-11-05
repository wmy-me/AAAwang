"""Persist weather forecast snapshots per run."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261105_0018"
down_revision: str | None = "20261104_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "weather_snapshots",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("task_revision_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("city", sa.String(length=120), nullable=False),
        sa.Column("source_service", sa.String(length=64), nullable=False),
        sa.Column("source_tool", sa.String(length=128), nullable=False),
        sa.Column("queried_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("forecasts", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["task_revision_id"], ["task_revisions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index("ix_weather_snapshots_owner_id", "weather_snapshots", ["owner_id"])
    op.create_index("ix_weather_snapshots_task_id", "weather_snapshots", ["task_id"])
    op.create_index(
        "ix_weather_snapshots_task_revision",
        "weather_snapshots",
        ["task_id", "revision"],
    )


def downgrade() -> None:
    op.drop_index("ix_weather_snapshots_task_revision", table_name="weather_snapshots")
    op.drop_index("ix_weather_snapshots_task_id", table_name="weather_snapshots")
    op.drop_index("ix_weather_snapshots_owner_id", table_name="weather_snapshots")
    op.drop_table("weather_snapshots")
