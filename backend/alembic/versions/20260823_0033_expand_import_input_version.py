"""Expand import input version for algorithm-prefixed hashes.

Revision ID: 20260823_0033
Revises: 20260823_0032
"""

from alembic import op
import sqlalchemy as sa


revision = "20260823_0033"
down_revision = "20260823_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "knowledge_import_runs",
        "input_version",
        existing_type=sa.String(64),
        type_=sa.String(80),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "knowledge_import_runs",
        "input_version",
        existing_type=sa.String(80),
        type_=sa.String(64),
        existing_nullable=False,
    )
