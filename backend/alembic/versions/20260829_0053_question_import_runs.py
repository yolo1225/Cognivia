"""Add independent XLSX question import staging.

Revision ID: 20260829_0053
Revises: 20260829_0052
"""

from alembic import op
import sqlalchemy as sa


revision = "20260829_0053"
down_revision = "20260829_0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "diagnostic_questions",
        sa.Column("external_id", sa.String(length=128), nullable=True),
    )
    op.execute(
        "UPDATE diagnostic_questions SET external_id = public_id WHERE external_id IS NULL"
    )
    op.create_unique_constraint(
        "uq_diagnostic_questions_domain_external",
        "diagnostic_questions",
        ["domain_code", "external_id"],
    )
    op.create_table(
        "question_import_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("domain_code", sa.String(length=64), nullable=False),
        sa.Column("template_version", sa.String(length=64), nullable=False),
        sa.Column("knowledge_catalog_fingerprint", sa.String(length=80), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("valid_row_count", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index("ix_question_import_runs_public_id", "question_import_runs", ["public_id"])
    op.create_index("ix_question_import_runs_domain_code", "question_import_runs", ["domain_code"])
    op.create_index("ix_question_import_runs_file_sha256", "question_import_runs", ["file_sha256"])
    op.create_index("ix_question_import_runs_status", "question_import_runs", ["status"])
    op.create_index(
        "ix_question_import_runs_domain_status",
        "question_import_runs",
        ["domain_code", "status"],
    )
    op.create_table(
        "question_import_rows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("question_external_id", sa.String(length=128), nullable=False),
        sa.Column("slot_key", sa.String(length=160), nullable=False),
        sa.Column("knowledge_ref", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("candidate_sources_json", sa.JSON(), nullable=False),
        sa.Column("source_binding_json", sa.JSON(), nullable=False),
        sa.Column("certification_report_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("validation_errors_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["question_import_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint("run_id", "row_number", name="uq_question_import_rows_run_number"),
        sa.UniqueConstraint(
            "run_id", "question_external_id", name="uq_question_import_rows_run_external"
        ),
    )
    op.create_index("ix_question_import_rows_public_id", "question_import_rows", ["public_id"])
    op.create_index("ix_question_import_rows_run_id", "question_import_rows", ["run_id"])
    op.create_index("ix_question_import_rows_question_external_id", "question_import_rows", ["question_external_id"])
    op.create_index("ix_question_import_rows_knowledge_ref", "question_import_rows", ["knowledge_ref"])
    op.create_index("ix_question_import_rows_status", "question_import_rows", ["status"])


def downgrade() -> None:
    op.drop_table("question_import_rows")
    op.drop_table("question_import_runs")
    op.drop_constraint("uq_diagnostic_questions_domain_external", "diagnostic_questions", type_="unique")
    op.drop_column("diagnostic_questions", "external_id")
