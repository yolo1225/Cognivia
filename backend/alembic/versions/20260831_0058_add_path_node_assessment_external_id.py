"""Align path-node assessment identity with the runtime model.

Revision ID: 20260831_0058
Revises: 20260831_0057
"""

import sqlalchemy as sa
from alembic import op


revision = "20260831_0058"
down_revision = "20260831_0057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "path_node_assessments",
        sa.Column("external_id", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("path_node_assessments", "external_id")
