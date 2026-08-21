"""Persist structured resource content for interactive rendering.

Revision ID: 20260816_0014
Revises: 20260816_0013
"""

from alembic import op
import sqlalchemy as sa


revision = "20260816_0014"
down_revision = "20260816_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "learning_resources",
        sa.Column("structured_content_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("learning_resources", "structured_content_json")
