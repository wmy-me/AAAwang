"""Retire the pre-Mem0 preference table without deleting its data."""

from collections.abc import Sequence

from alembic import op

revision: str = "20261106_0022"
down_revision: str | None = "20261106_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 0021 was an unshipped local store. Keep any existing rows recoverable but
    # make clear that Mem0/pgvector is now the single live preference source.
    op.rename_table("user_preferences", "legacy_user_preferences_pre_mem0")


def downgrade() -> None:
    op.rename_table("legacy_user_preferences_pre_mem0", "user_preferences")
