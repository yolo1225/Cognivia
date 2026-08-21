"""M1 structured knowledge import candidates.

Revision ID: 20260819_0018
Revises: 20260819_0017
"""

from alembic import op
import sqlalchemy as sa


revision = "20260819_0018"
down_revision = "20260819_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_items",
        sa.Column(
            "ability_weights_json", sa.JSON(), nullable=False, server_default=sa.text("('{}')")
        ),
    )
    op.add_column(
        "knowledge_items",
        sa.Column(
            "source_locator_json", sa.JSON(), nullable=False, server_default=sa.text("('{}')")
        ),
    )
    op.add_column(
        "knowledge_items",
        sa.Column("status", sa.String(32), nullable=False, server_default="published"),
    )
    op.create_index("ix_knowledge_items_status", "knowledge_items", ["status"])
    op.create_table(
        "knowledge_import_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(64), nullable=False),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("domain_code", sa.String(64), nullable=False),
        sa.Column("candidate_type", sa.String(32), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("source_locator_json", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("validation_errors_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("public_id", "document_id", "domain_code", "candidate_type", "status"):
        op.create_index(
            f"ix_knowledge_import_candidates_{column}",
            "knowledge_import_candidates",
            [column],
            unique=column == "public_id",
        )


def downgrade() -> None:
    op.drop_table("knowledge_import_candidates")
    op.drop_index("ix_knowledge_items_status", table_name="knowledge_items")
    op.drop_column("knowledge_items", "status")
    op.drop_column("knowledge_items", "source_locator_json")
    op.drop_column("knowledge_items", "ability_weights_json")
