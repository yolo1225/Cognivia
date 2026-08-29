"""Scope tutoring sessions by product context.

Revision ID: 20260828_0051
Revises: 20260828_0050
"""

from alembic import op
import sqlalchemy as sa


revision = "20260828_0051"
down_revision = "20260828_0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tutoring_sessions",
        sa.Column("context_type", sa.String(length=32), nullable=False, server_default="resource"),
    )
    op.add_column(
        "tutoring_sessions",
        sa.Column("context_ref_id", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_tutoring_sessions_context_type", "tutoring_sessions", ["context_type"])
    op.create_index("ix_tutoring_sessions_context_ref_id", "tutoring_sessions", ["context_ref_id"])


def downgrade() -> None:
    op.drop_index("ix_tutoring_sessions_context_ref_id", table_name="tutoring_sessions")
    op.drop_index("ix_tutoring_sessions_context_type", table_name="tutoring_sessions")
    op.drop_column("tutoring_sessions", "context_ref_id")
    op.drop_column("tutoring_sessions", "context_type")
