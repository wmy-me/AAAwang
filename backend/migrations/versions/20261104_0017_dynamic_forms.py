"""Add bounded dynamic task form proposals."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261104_0017"
down_revision: str | None = "20261104_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dynamic_form_proposals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("task_revision_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("schema", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("confirmed_values", sa.JSON(), nullable=True),
        sa.Column("client_request_id", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_revision_id"], ["task_revisions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "task_revision_id", name="uq_form_proposals_task_revision"),
        sa.UniqueConstraint("task_id", "client_request_id", name="uq_form_proposals_task_request"),
    )
    op.create_index("ix_dynamic_form_proposals_task_id", "dynamic_form_proposals", ["task_id"])
    op.create_index("ix_form_proposals_task_created", "dynamic_form_proposals", ["task_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_form_proposals_task_created", table_name="dynamic_form_proposals")
    op.drop_index("ix_dynamic_form_proposals_task_id", table_name="dynamic_form_proposals")
    op.drop_table("dynamic_form_proposals")