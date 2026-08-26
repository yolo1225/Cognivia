"""Allow formal questions to cover related knowledge items.

Revision ID: 20260825_0037
Revises: 20260825_0036
"""

from alembic import op
import sqlalchemy as sa


revision = "20260825_0037"
down_revision = "20260825_0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "diagnostic_questions",
        sa.Column("related_knowledge_ids_json", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("diagnostic_questions", "related_knowledge_ids_json")
