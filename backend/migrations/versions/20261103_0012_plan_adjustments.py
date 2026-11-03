"""Persist immutable manual shopping-plan adjustments."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261103_0012"
down_revision: str | None = "20261103_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shopping_plan_adjustments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("task_revision_id", sa.Uuid(), nullable=False),
        sa.Column("base_run_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("client_request_id", sa.String(128), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("people", sa.Integer(), nullable=False),
        sa.Column("covered_people", sa.Integer(), nullable=False),
        sa.Column("budget", sa.Numeric(12, 2), nullable=False),
        sa.Column("total", sa.Numeric(12, 2), nullable=False),
        sa.Column("remaining", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("unknown_fees", sa.Boolean(), nullable=False),
        sa.Column("note", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_revision_id"], ["task_revisions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["base_run_id"], ["runs.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("task_id", "version", name="uq_plan_adjustments_task_version"),
        sa.UniqueConstraint("task_id", "client_request_id", name="uq_plan_adjustments_task_request"),
    )
    op.create_index(
        "ix_shopping_plan_adjustments_owner_id", "shopping_plan_adjustments", ["owner_id"]
    )
    op.create_index(
        "ix_shopping_plan_adjustments_task_id", "shopping_plan_adjustments", ["task_id"]
    )
    op.create_index(
        "ix_plan_adjustments_task_current", "shopping_plan_adjustments", ["task_id", "is_current"]
    )
    op.create_table(
        "shopping_plan_adjustment_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("adjustment_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("package_quantity", sa.Integer(), nullable=False),
        sa.Column("covered_people", sa.Integer(), nullable=False),
        sa.Column("subtotal", sa.Numeric(12, 2), nullable=False),
        sa.ForeignKeyConstraint(
            ["adjustment_id"], ["shopping_plan_adjustments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["shopping_candidates.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "adjustment_id", "candidate_id", name="uq_plan_adjustment_items_candidate"
        ),
    )
    op.create_index(
        "ix_shopping_plan_adjustment_items_adjustment_id",
        "shopping_plan_adjustment_items",
        ["adjustment_id"],
    )


def downgrade() -> None:
    op.drop_table("shopping_plan_adjustment_items")
    op.drop_table("shopping_plan_adjustments")
