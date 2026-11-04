"""Persist map POI snapshots per run."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261104_0014"
down_revision: str | None = "20261103_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "map_places",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("task_revision_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("place_key", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("address", sa.String(length=240), nullable=True),
        sa.Column("location", sa.String(length=240), nullable=True),
        sa.Column("phone", sa.String(length=80), nullable=True),
        sa.Column("url", sa.String(length=240), nullable=True),
        sa.Column("query", sa.String(length=120), nullable=False),
        sa.Column("city", sa.String(length=120), nullable=False),
        sa.Column("source_service", sa.String(length=64), nullable=False),
        sa.Column("source_tool", sa.String(length=128), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_revision_id"], ["task_revisions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "place_key", name="uq_map_places_run_place"),
    )
    op.create_index("ix_map_places_run_id", "map_places", ["run_id"])
    op.create_index("ix_map_places_owner_id", "map_places", ["owner_id"])
    op.create_index("ix_map_places_task_id", "map_places", ["task_id"])
    op.create_index("ix_map_places_task_revision", "map_places", ["task_id", "revision"])


def downgrade() -> None:
    op.drop_index("ix_map_places_task_revision", table_name="map_places")
    op.drop_index("ix_map_places_task_id", table_name="map_places")
    op.drop_index("ix_map_places_owner_id", table_name="map_places")
    op.drop_index("ix_map_places_run_id", table_name="map_places")
    op.drop_table("map_places")
