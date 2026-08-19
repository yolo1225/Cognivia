"""M4B diagnostic scoring persistence.

Revision ID: 20260819_0017
Revises: 20260818_0016
"""

from alembic import op
import sqlalchemy as sa


revision = "20260819_0017"
down_revision = "20260818_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("answer_records", sa.Column("session_id", sa.String(64), nullable=True))
    op.add_column("answer_records", sa.Column("answer_text", sa.Text(), nullable=True))
    op.add_column(
        "answer_records",
        sa.Column("scoring_status", sa.String(32), nullable=False, server_default="scored"),
    )
    op.add_column(
        "answer_records",
        sa.Column("scoring_method", sa.String(32), nullable=False, server_default="legacy_keyword"),
    )
    op.add_column("answer_records", sa.Column("rubric_version", sa.String(32), nullable=True))
    op.add_column(
        "answer_records",
        sa.Column("scoring_detail_json", sa.JSON(), nullable=False, server_default=sa.text("('{}')")),
    )
    op.add_column(
        "answer_records",
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1"),
    )
    op.add_column(
        "answer_records",
        sa.Column("scoring_uncertain", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("answer_records", sa.Column("ai_comment", sa.Text(), nullable=True))
    op.execute(
        "UPDATE answer_records SET session_id=JSON_UNQUOTE(JSON_EXTRACT(answer_summary_json, '$.session_id')) "
        "WHERE JSON_EXTRACT(answer_summary_json, '$.session_id') IS NOT NULL"
    )
    op.create_index("ix_answer_records_session_id", "answer_records", ["session_id"])
    op.create_index("ix_answer_records_scoring_status", "answer_records", ["scoring_status"])
    op.create_unique_constraint(
        "uq_answer_records_session_question", "answer_records", ["session_id", "question_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_answer_records_session_question", "answer_records", type_="unique")
    op.drop_index("ix_answer_records_scoring_status", table_name="answer_records")
    op.drop_index("ix_answer_records_session_id", table_name="answer_records")
    for column in (
        "ai_comment",
        "scoring_uncertain",
        "confidence",
        "scoring_detail_json",
        "rubric_version",
        "scoring_method",
        "scoring_status",
        "answer_text",
        "session_id",
    ):
        op.drop_column("answer_records", column)
