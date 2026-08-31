"""Remove persisted formal-question certification and Chunk bindings.

Revision ID: 20260831_0057
Revises: 20260830_0056
"""

import sqlalchemy as sa
from alembic import op


revision = "20260831_0057"
down_revision = "20260830_0056"
branch_labels = None
depends_on = None


_ANSWER_KEY_PATHS = (
    "$.source_quote",
    "$.source_ref_ids",
    "$.source_locator",
    "$.source_locators",
    "$.source_content_hashes",
    "$.evidence_quotes",
    "$.chunker_version",
)


def upgrade() -> None:
    bind = op.get_bind()
    question_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("diagnostic_questions")
    }
    # Rejected/pending legacy certifications are neither published assessments
    # nor disabled history. Keep them visible to administrators as stale data
    # that must be replaced through the v3 XLSX template.
    if "certification_status" in question_columns:
        op.execute(
            """
            UPDATE diagnostic_questions
            SET status = 'stale'
            WHERE status <> 'disabled'
              AND certification_status IN ('pending', 'rejected', 'stale')
            """
        )
    if "answer_key_json" in question_columns:
        paths = ", ".join(f"'{path}'" for path in _ANSWER_KEY_PATHS)
        op.execute(
            f"""
            UPDATE diagnostic_questions
            SET answer_key_json = JSON_REMOVE(answer_key_json, {paths})
            WHERE answer_key_json IS NOT NULL
            """
        )
    op.execute(
        """
        UPDATE question_import_runs
        SET status = 'cancelled',
            error_summary = '题库导入规则已升级为 v3，请重新下载模板并上传。'
        WHERE status <> 'published'
        """
    )

    row_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("question_import_rows")
    }
    for column in (
        "candidate_sources_json",
        "source_binding_json",
        "certification_report_json",
    ):
        if column in row_columns:
            op.drop_column("question_import_rows", column)
    question_indexes = {
        index["name"] for index in sa.inspect(bind).get_indexes("diagnostic_questions")
    }
    if "ix_diagnostic_questions_certification_status" in question_indexes:
        op.drop_index(
            "ix_diagnostic_questions_certification_status",
            table_name="diagnostic_questions",
        )
    for column in (
        "certification_status",
        "certification_rule_version",
        "certification_report_json",
        "source_content_hash",
        "certified_at",
    ):
        if column in question_columns:
            op.drop_column("diagnostic_questions", column)


def downgrade() -> None:
    raise NotImplementedError("Question certification removal is intentionally irreversible")
