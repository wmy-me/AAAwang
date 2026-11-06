"""private wiki documents and pages

Revision ID: 20261106_0023
Revises: 20261106_0022
"""
from alembic import op
import sqlalchemy as sa

revision = "20261106_0023"
down_revision = "20261106_0022"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("wiki_documents", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("filename", sa.String(255), nullable=False), sa.Column("content_hash", sa.String(64), nullable=False), sa.Column("content", sa.Text(), nullable=False), sa.Column("status", sa.String(24), nullable=False), sa.Column("error_summary", sa.String(500)), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.UniqueConstraint("owner_id", "content_hash", name="uq_wiki_document_owner_hash"))
    op.create_index("ix_wiki_documents_owner_id", "wiki_documents", ["owner_id"])
    op.create_table("wiki_pages", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("document_id", sa.Uuid(), sa.ForeignKey("wiki_documents.id", ondelete="CASCADE"), nullable=False, unique=True), sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("title", sa.String(255), nullable=False), sa.Column("content", sa.Text(), nullable=False), sa.Column("source_excerpt", sa.Text(), nullable=False), sa.Column("status", sa.String(24), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.create_index("ix_wiki_pages_owner_id", "wiki_pages", ["owner_id"])
def downgrade():
    op.drop_table("wiki_pages"); op.drop_table("wiki_documents")
