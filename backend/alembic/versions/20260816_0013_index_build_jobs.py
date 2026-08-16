"""Add persisted candidate index rebuild job records.

Revision ID: 20260816_0013
Revises: 20260816_0012
"""

from alembic import op
import sqlalchemy as sa


revision = "20260816_0013"
down_revision = "20260816_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "index_build_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("domain_code", sa.String(64), nullable=False, index=True),
        sa.Column("status", sa.String(32), nullable=False, index=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("index_build_jobs")
