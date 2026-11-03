"""Persist shopping candidate snapshots and validated plans."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261103_0011"
down_revision: str | None = "20261103_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shopping_candidates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("task_revision_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.String(128), nullable=False),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("unit", sa.String(120), nullable=False),
        sa.Column("distributable_units", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_service", sa.String(64), nullable=False),
        sa.Column("simulated", sa.Boolean(), nullable=False),
        sa.Column("availability", sa.String(120), nullable=False),
        sa.Column("quoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("queried_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_revision_id"], ["task_revisions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("run_id", "product_id", name="uq_candidates_run_product"),
    )
    op.create_index("ix_shopping_candidates_run_id", "shopping_candidates", ["run_id"])
    op.create_index("ix_shopping_candidates_owner_id", "shopping_candidates", ["owner_id"])
    op.create_index("ix_shopping_candidates_task_id", "shopping_candidates", ["task_id"])
    op.create_index("ix_candidates_task_revision", "shopping_candidates", ["task_id", "revision"])
    op.create_table(
        "shopping_plans",
        sa.Column("run_id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("task_revision_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("people", sa.Integer(), nullable=False),
        sa.Column("covered_people", sa.Integer(), nullable=False),
        sa.Column("budget", sa.Numeric(12, 2), nullable=False),
        sa.Column("total", sa.Numeric(12, 2), nullable=False),
        sa.Column("remaining", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("unknown_fees", sa.Boolean(), nullable=False),
        sa.Column("note", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_revision_id"], ["task_revisions.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_shopping_plans_owner_id", "shopping_plans", ["owner_id"])
    op.create_index("ix_shopping_plans_task_id", "shopping_plans", ["task_id"])
    op.create_table(
        "shopping_plan_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("package_quantity", sa.Integer(), nullable=False),
        sa.Column("covered_people", sa.Integer(), nullable=False),
        sa.Column("subtotal", sa.Numeric(12, 2), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["shopping_plans.run_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_id"], ["shopping_candidates.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("run_id", "candidate_id", name="uq_plan_items_candidate"),
    )
    op.create_index("ix_shopping_plan_items_run_id", "shopping_plan_items", ["run_id"])


def downgrade() -> None:
    op.drop_table("shopping_plan_items")
    op.drop_table("shopping_plans")
    op.drop_table("shopping_candidates")
