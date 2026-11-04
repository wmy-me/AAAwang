"""Persist trusted capability choices for each run."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261104_0015"
down_revision: str | None = "20261104_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("capability_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "capability_ids")