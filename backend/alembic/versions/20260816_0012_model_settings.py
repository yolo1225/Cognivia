"""Add runtime-editable model gateway configuration.

Revision ID: 20260816_0012
Revises: 20260815_0011
"""

from alembic import op
import sqlalchemy as sa


revision = "20260816_0012"
down_revision = "20260815_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_configs",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("model_configs")
