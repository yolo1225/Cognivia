"""Align runtime-required columns and indexes with the ORM.

Revision ID: 20260831_0059
Revises: 20260831_0058
"""

from alembic import op
import sqlalchemy as sa


revision = "20260831_0059"
down_revision = "20260831_0058"
branch_labels = None
depends_on = None


def _require_json(table: str, column: str, empty_json: str) -> None:
    op.execute(f"UPDATE {table} SET {column} = {empty_json} WHERE {column} IS NULL")
    op.alter_column(table, column, existing_type=sa.JSON(), nullable=False)


def upgrade() -> None:
    _require_json("generation_tasks", "package_coverage_json", "JSON_OBJECT()")
    _require_json("learning_resources", "knowledge_coverage_json", "JSON_OBJECT()")
    _require_json("learning_resources", "structured_content_json", "JSON_OBJECT()")
    _require_json("review_reports", "target_knowledge_ids_json", "JSON_ARRAY()")
    _require_json("review_reports", "covered_knowledge_ids_json", "JSON_ARRAY()")
    _require_json("review_reports", "missing_knowledge_ids_json", "JSON_ARRAY()")
    op.alter_column("users", "username", existing_type=sa.String(length=32), nullable=False)
    op.alter_column("users", "password_hash", existing_type=sa.String(length=255), nullable=False)
    op.create_index("ix_learner_profiles_profile_source", "learner_profiles", ["profile_source"])
    op.create_index(
        "ix_learner_profiles_diagnosis_completed", "learner_profiles", ["diagnosis_completed"]
    )
    op.create_index(
        "ix_question_import_runs_knowledge_catalog_fingerprint",
        "question_import_runs",
        ["knowledge_catalog_fingerprint"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_question_import_runs_knowledge_catalog_fingerprint",
        table_name="question_import_runs",
    )
    op.drop_index("ix_learner_profiles_diagnosis_completed", table_name="learner_profiles")
    op.drop_index("ix_learner_profiles_profile_source", table_name="learner_profiles")
    op.alter_column("users", "password_hash", existing_type=sa.String(length=255), nullable=True)
    op.alter_column("users", "username", existing_type=sa.String(length=32), nullable=True)
    for table, column in (
        ("review_reports", "missing_knowledge_ids_json"),
        ("review_reports", "covered_knowledge_ids_json"),
        ("review_reports", "target_knowledge_ids_json"),
        ("learning_resources", "structured_content_json"),
        ("learning_resources", "knowledge_coverage_json"),
        ("generation_tasks", "package_coverage_json"),
    ):
        op.alter_column(table, column, existing_type=sa.JSON(), nullable=True)
