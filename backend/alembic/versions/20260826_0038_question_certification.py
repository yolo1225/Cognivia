"""Add formal question certification lifecycle.

Revision ID: 20260826_0038
Revises: 20260825_0037
"""

from alembic import op
import sqlalchemy as sa


revision = "20260826_0038"
down_revision = "20260825_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "diagnostic_questions",
        sa.Column(
            "certification_status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "diagnostic_questions",
        sa.Column("certification_rule_version", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "diagnostic_questions",
        sa.Column(
            "certification_report_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("('{}')"),
        ),
    )
    op.add_column(
        "diagnostic_questions",
        sa.Column("source_content_hash", sa.String(length=71), nullable=True),
    )
    op.add_column(
        "diagnostic_questions",
        sa.Column("certified_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_diagnostic_questions_certification_status",
        "diagnostic_questions",
        ["certification_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_diagnostic_questions_certification_status",
        table_name="diagnostic_questions",
    )
    op.drop_column("diagnostic_questions", "certified_at")
    op.drop_column("diagnostic_questions", "source_content_hash")
    op.drop_column("diagnostic_questions", "certification_report_json")
    op.drop_column("diagnostic_questions", "certification_rule_version")
    op.drop_column("diagnostic_questions", "certification_status")
