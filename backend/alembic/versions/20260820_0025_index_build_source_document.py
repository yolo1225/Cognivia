"""Bind candidate index builds to imports and index domain status.

Revision ID: 20260820_0025
Revises: 20260820_0024
"""

from alembic import op
import sqlalchemy as sa


revision = "20260820_0025"
down_revision = "20260820_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "index_build_jobs",
        sa.Column("source_document_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_index_build_jobs_source_document_id",
        "index_build_jobs",
        "knowledge_documents",
        ["source_document_id"],
        ["id"],
    )
    op.create_index(
        "ix_index_build_jobs_source_document_id",
        "index_build_jobs",
        ["source_document_id"],
        unique=False,
    )
    op.create_index(
        "ix_index_build_jobs_domain_status",
        "index_build_jobs",
        ["domain_code", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_index_build_jobs_domain_status", table_name="index_build_jobs")
    op.drop_index("ix_index_build_jobs_source_document_id", table_name="index_build_jobs")
    op.drop_constraint(
        "fk_index_build_jobs_source_document_id",
        "index_build_jobs",
        type_="foreignkey",
    )
    op.drop_column("index_build_jobs", "source_document_id")
