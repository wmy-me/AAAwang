"""Persist bounded public web search source snapshots."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261105_0019"
down_revision: str | None = "20261105_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "web_search_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("task_revision_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("result_key", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("url", sa.String(length=2000), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("published_at", sa.String(length=80), nullable=True),
        sa.Column("source_service", sa.String(length=64), nullable=False),
        sa.Column("source_tool", sa.String(length=128), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["task_revision_id"], ["task_revisions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "result_key", name="uq_web_search_run_result"),
    )
    op.create_index("ix_web_search_results_run_id", "web_search_results", ["run_id"])
    op.create_index("ix_web_search_results_owner_id", "web_search_results", ["owner_id"])
    op.create_index("ix_web_search_results_task_id", "web_search_results", ["task_id"])
    op.create_index(
        "ix_web_search_task_revision", "web_search_results", ["task_id", "revision"]
    )


def downgrade() -> None:
    op.drop_index("ix_web_search_task_revision", table_name="web_search_results")
    op.drop_index("ix_web_search_results_task_id", table_name="web_search_results")
    op.drop_index("ix_web_search_results_owner_id", table_name="web_search_results")
    op.drop_index("ix_web_search_results_run_id", table_name="web_search_results")
    op.drop_table("web_search_results")
