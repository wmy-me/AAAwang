"""Allow task revision deletion to cascade to its bound runs."""

from collections.abc import Sequence

from alembic import op

revision: str = "20261103_0006"
down_revision: str | None = "20261103_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("runs_task_revision_id_fkey", "runs", type_="foreignkey")
    op.create_foreign_key(
        "runs_task_revision_id_fkey",
        "runs",
        "task_revisions",
        ["task_revision_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("runs_task_revision_id_fkey", "runs", type_="foreignkey")
    op.create_foreign_key(
        "runs_task_revision_id_fkey",
        "runs",
        "task_revisions",
        ["task_revision_id"],
        ["id"],
        ondelete="RESTRICT",
    )