"""Add lifecycle fields for formal question-bank questions.

Revision ID: 20260825_0036
Revises: 20260825_0035
"""

from alembic import op
import sqlalchemy as sa


revision = "20260825_0036"
down_revision = "20260825_0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "diagnostic_questions",
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
    )
    op.add_column(
        "diagnostic_questions", sa.Column("disabled_at", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "diagnostic_questions",
        sa.Column("disabled_reason", sa.String(255), nullable=True),
    )
    op.create_index(
        "ix_diagnostic_questions_status", "diagnostic_questions", ["status"]
    )


def downgrade() -> None:
    op.drop_index("ix_diagnostic_questions_status", table_name="diagnostic_questions")
    op.drop_column("diagnostic_questions", "disabled_reason")
    op.drop_column("diagnostic_questions", "disabled_at")
    op.drop_column("diagnostic_questions", "status")
