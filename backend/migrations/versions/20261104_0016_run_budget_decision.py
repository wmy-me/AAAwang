"""Persist model decision and shared Run budget summaries."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261104_0016"
down_revision: str | None = "20261104_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("decision", sa.JSON(), nullable=True))
    op.add_column("runs", sa.Column("budget", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "budget")
    op.drop_column("runs", "decision")