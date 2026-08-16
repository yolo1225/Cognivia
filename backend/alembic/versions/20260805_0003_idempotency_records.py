"""add idempotency records

Revision ID: 20260805_0003
Revises: 20260716_0002
Create Date: 2026-08-05
"""

from alembic import op
import sqlalchemy as sa


revision = "20260805_0003"
down_revision = "20260716_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(length=96), nullable=False),
        sa.Column("request_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=True),
        sa.Column("entity_public_id", sa.String(length=128), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope", "request_key", name="uq_idempotency_scope_request_key"),
    )
    op.create_index("ix_idempotency_records_scope", "idempotency_records", ["scope"])


def downgrade() -> None:
    op.drop_index("ix_idempotency_records_scope", table_name="idempotency_records")
    op.drop_table("idempotency_records")
