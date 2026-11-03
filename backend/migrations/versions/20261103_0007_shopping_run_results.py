"""Add controlled shopping execution and persisted results."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261103_0007"
down_revision: str | None = "20261103_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column("execution_type", sa.String(length=32), nullable=False, server_default="diagnostic"),
    )
    op.alter_column("runs", "execution_type", server_default=None)
    op.create_table(
        "shopping_run_results",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("source", sa.JSON(), nullable=False),
        sa.Column("execution_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id"),
    )


def downgrade() -> None:
    op.drop_table("shopping_run_results")
    op.drop_column("runs", "execution_type")