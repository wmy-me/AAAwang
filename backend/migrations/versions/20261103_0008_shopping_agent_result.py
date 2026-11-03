"""Persist shopping agent decision metadata."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261103_0008"
down_revision: str | None = "20261103_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "shopping_run_results",
        sa.Column("decision_type", sa.String(length=32), nullable=False, server_default="delegated_discovery"),
    )
    op.add_column(
        "shopping_run_results",
        sa.Column("delegated", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "shopping_run_results",
        sa.Column("mcp_call_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("shopping_run_results", "decision_type", server_default=None)
    op.alter_column("shopping_run_results", "delegated", server_default=None)
    op.alter_column("shopping_run_results", "mcp_call_count", server_default=None)


def downgrade() -> None:
    op.drop_column("shopping_run_results", "mcp_call_count")
    op.drop_column("shopping_run_results", "delegated")
    op.drop_column("shopping_run_results", "decision_type")
