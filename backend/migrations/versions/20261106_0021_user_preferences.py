"""Add explicit owner-scoped long-term preferences."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261106_0021"
down_revision: str | None = "20261105_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_preferences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("preference_key", sa.String(length=120), nullable=False),
        sa.Column("content", sa.String(length=500), nullable=False),
        sa.Column("source_message_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "category", "preference_key", name="uq_preferences_owner_category_key"),
        sa.UniqueConstraint("owner_id", "source_message_id", name="uq_preferences_owner_source_message"),
    )
    op.create_index("ix_user_preferences_owner_id", "user_preferences", ["owner_id"])
    op.create_index("ix_preferences_owner_status_updated", "user_preferences", ["owner_id", "status", sa.text("updated_at DESC")])


def downgrade() -> None:
    op.drop_index("ix_preferences_owner_status_updated", table_name="user_preferences")
    op.drop_index("ix_user_preferences_owner_id", table_name="user_preferences")
    op.drop_table("user_preferences")
