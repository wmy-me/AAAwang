"""Allow one user and one assistant message to reference the same run."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261103_0010"
down_revision: str | None = "20261103_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_messages_run_id", "messages", type_="unique")
    op.create_index(
        "uq_messages_assistant_run_id",
        "messages",
        ["run_id"],
        unique=True,
        postgresql_where=sa.text("role = 'assistant'"),
    )


def downgrade() -> None:
    op.drop_index("uq_messages_assistant_run_id", table_name="messages")
    op.create_unique_constraint("uq_messages_run_id", "messages", ["run_id"])
