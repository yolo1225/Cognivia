"""Add staged domain change sets and question-inventory template snapshots.

Revision ID: 20260830_0054
Revises: 20260829_0053
"""

from alembic import op
import sqlalchemy as sa


revision = "20260830_0054"
down_revision = "20260829_0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "domain_change_sets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("domain_code", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("base_catalog_fingerprint", sa.String(length=80), nullable=False),
        sa.Column("target_catalog_fingerprint", sa.String(length=80), nullable=True),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index("ix_domain_change_sets_public_id", "domain_change_sets", ["public_id"])
    op.create_index("ix_domain_change_sets_domain_code", "domain_change_sets", ["domain_code"])
    op.create_index("ix_domain_change_sets_status", "domain_change_sets", ["status"])
    op.create_index(
        "ix_domain_change_sets_domain_status", "domain_change_sets", ["domain_code", "status"]
    )

    op.add_column("knowledge_documents", sa.Column("change_set_id", sa.Integer(), nullable=True))
    op.add_column(
        "knowledge_documents", sa.Column("import_mode", sa.String(length=16), nullable=False, server_default="append")
    )
    op.add_column("knowledge_documents", sa.Column("replaces_document_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_knowledge_documents_change_set", "knowledge_documents", "domain_change_sets", ["change_set_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_knowledge_documents_replaces_document", "knowledge_documents", "knowledge_documents", ["replaces_document_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_knowledge_documents_change_set_id", "knowledge_documents", ["change_set_id"])
    op.create_index("ix_knowledge_documents_import_mode", "knowledge_documents", ["import_mode"])
    op.create_index("ix_knowledge_documents_replaces_document_id", "knowledge_documents", ["replaces_document_id"])

    op.add_column("knowledge_import_runs", sa.Column("change_set_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_knowledge_import_runs_change_set", "knowledge_import_runs", "domain_change_sets", ["change_set_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_knowledge_import_runs_change_set_id", "knowledge_import_runs", ["change_set_id"])

    op.add_column(
        "question_import_runs", sa.Column("question_inventory_fingerprint", sa.String(length=80), nullable=False, server_default="")
    )
    # MySQL does not accept a literal default for JSON on all supported 8.x
    # versions. Backfill explicitly before making the column mandatory.
    op.add_column("question_import_runs", sa.Column("scope_json", sa.JSON(), nullable=True))
    op.execute("UPDATE question_import_runs SET scope_json = JSON_ARRAY() WHERE scope_json IS NULL")
    op.alter_column("question_import_runs", "scope_json", nullable=False, existing_type=sa.JSON())
    op.add_column("question_import_runs", sa.Column("change_set_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_question_import_runs_change_set", "question_import_runs", "domain_change_sets", ["change_set_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_question_import_runs_question_inventory_fingerprint", "question_import_runs", ["question_inventory_fingerprint"])
    op.create_index("ix_question_import_runs_change_set_id", "question_import_runs", ["change_set_id"])


def downgrade() -> None:
    op.drop_index("ix_question_import_runs_change_set_id", table_name="question_import_runs")
    op.drop_index("ix_question_import_runs_question_inventory_fingerprint", table_name="question_import_runs")
    op.drop_constraint("fk_question_import_runs_change_set", "question_import_runs", type_="foreignkey")
    op.drop_column("question_import_runs", "change_set_id")
    op.drop_column("question_import_runs", "scope_json")
    op.drop_column("question_import_runs", "question_inventory_fingerprint")
    op.drop_index("ix_knowledge_import_runs_change_set_id", table_name="knowledge_import_runs")
    op.drop_constraint("fk_knowledge_import_runs_change_set", "knowledge_import_runs", type_="foreignkey")
    op.drop_column("knowledge_import_runs", "change_set_id")
    op.drop_index("ix_knowledge_documents_replaces_document_id", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_import_mode", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_change_set_id", table_name="knowledge_documents")
    op.drop_constraint("fk_knowledge_documents_replaces_document", "knowledge_documents", type_="foreignkey")
    op.drop_constraint("fk_knowledge_documents_change_set", "knowledge_documents", type_="foreignkey")
    op.drop_column("knowledge_documents", "replaces_document_id")
    op.drop_column("knowledge_documents", "import_mode")
    op.drop_column("knowledge_documents", "change_set_id")
    op.drop_index("ix_domain_change_sets_domain_status", table_name="domain_change_sets")
    op.drop_table("domain_change_sets")
