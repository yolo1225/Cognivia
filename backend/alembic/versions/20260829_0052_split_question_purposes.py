"""Split active questions into three exclusive purposes.

Revision ID: 20260829_0052
Revises: 20260828_0051
"""

from alembic import op


revision = "20260829_0052"
down_revision = "20260828_0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE diagnostic_questions
        SET answer_key_json = JSON_SET(
            answer_key_json,
            '$.question_bank_uses',
            CASE
                WHEN JSON_EXTRACT(answer_key_json, '$.question_slot') IS NULL
                    THEN JSON_ARRAY('diagnosis')
                WHEN JSON_CONTAINS(
                    JSON_EXTRACT(answer_key_json, '$.question_bank_uses'),
                    JSON_QUOTE('mastery_validation')
                ) THEN JSON_ARRAY('mastery_validation')
                ELSE JSON_ARRAY('graded_quiz')
            END
        )
        WHERE status = 'active'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE diagnostic_questions
        SET answer_key_json = JSON_SET(
            answer_key_json,
            '$.question_bank_uses',
            CASE
                WHEN JSON_CONTAINS(
                    JSON_EXTRACT(answer_key_json, '$.question_bank_uses'),
                    JSON_QUOTE('mastery_validation')
                ) THEN JSON_ARRAY('mastery_validation', 'mistake_consolidation')
                ELSE JSON_ARRAY('diagnosis', 'graded_quiz')
            END
        )
        WHERE status = 'active'
        """
    )
