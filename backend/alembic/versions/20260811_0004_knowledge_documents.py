"""Add domain-scoped RAG knowledge documents.

Revision ID: 20260811_0004
Revises: 20260805_0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0004"
down_revision: str | None = "20260805_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(64), nullable=False),
        sa.Column("domain_code", sa.String(64), nullable=False),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("stored_path", sa.String(1024), nullable=True),
        sa.Column("file_type", sa.String(32), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False, server_default="application/octet-stream"),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("knowledge_item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embedding_model", sa.String(255), nullable=True),
        sa.Column("source_title", sa.String(255), nullable=False, server_default=""),
        sa.Column("license_note", sa.String(255), nullable=False, server_default=""),
        sa.Column("uploaded_by", sa.String(64), nullable=False, server_default="demo_admin"),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index("ix_knowledge_documents_public_id", "knowledge_documents", ["public_id"], unique=True)
    op.create_index("ix_knowledge_documents_domain_code", "knowledge_documents", ["domain_code"])
    op.create_index("ix_knowledge_documents_sha256", "knowledge_documents", ["sha256"])
    op.create_index("ix_knowledge_documents_status", "knowledge_documents", ["status"])
    with op.batch_alter_table("knowledge_items") as batch:
        batch.add_column(sa.Column("source_document_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_knowledge_items_source_document",
            "knowledge_documents",
            ["source_document_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_knowledge_items_source_document_id", ["source_document_id"])

    connection = op.get_bind()
    item_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM knowledge_items WHERE domain_code = 'ai_app_dev'")
    ).scalar_one()
    if item_count:
        connection.execute(
            sa.text(
                """
                INSERT INTO knowledge_documents
                (public_id, domain_code, original_name, stored_path, file_type, mime_type,
                 size_bytes, sha256, status, knowledge_item_count, chunk_count,
                 source_title, license_note, uploaded_by, created_at, updated_at)
                VALUES
                ('kdoc_ai_app_dev_seed', 'ai_app_dev', 'AI应用开发核心知识包.json', NULL,
                 'seed_package', 'application/json', 0, 'seed-ai-app-dev-core-v1', 'ready',
                 :item_count, :item_count, 'AI 应用开发核心知识包', '项目内置种子知识',
                 'system', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            ),
            {"item_count": item_count},
        )
        connection.execute(
            sa.text(
                "UPDATE knowledge_items SET source_document_id = "
                "(SELECT id FROM knowledge_documents WHERE public_id = 'kdoc_ai_app_dev_seed') "
                "WHERE domain_code = 'ai_app_dev' AND source_document_id IS NULL"
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("knowledge_items") as batch:
        batch.drop_index("ix_knowledge_items_source_document_id")
        batch.drop_constraint("fk_knowledge_items_source_document", type_="foreignkey")
        batch.drop_column("source_document_id")
    op.drop_index("ix_knowledge_documents_status", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_sha256", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_domain_code", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_public_id", table_name="knowledge_documents")
    op.drop_table("knowledge_documents")
