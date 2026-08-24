"""Add resumable knowledge import batches.

Revision ID: 20260824_0034
Revises: 20260823_0033
"""

from alembic import op
import sqlalchemy as sa


revision = "20260824_0034"
down_revision = "20260823_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_import_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("step", sa.String(64), nullable=False),
        sa.Column("batch_key", sa.String(128), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reuse_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_owner", sa.String(64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("artifact_json", sa.JSON(), nullable=False),
        sa.Column("artifact_hash", sa.String(64), nullable=True),
        sa.Column("model_name", sa.String(255), nullable=True),
        sa.Column("tokens_input", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_output", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["run_id"], ["knowledge_import_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "run_id", "step", "batch_key", "input_hash",
            name="uq_knowledge_import_batch_input",
        ),
    )
    op.create_index("ix_knowledge_import_batches_run_id", "knowledge_import_batches", ["run_id"])
    op.create_index("ix_knowledge_import_batches_step", "knowledge_import_batches", ["step"])
    op.create_index("ix_knowledge_import_batches_status", "knowledge_import_batches", ["status"])
    op.create_index(
        "ix_import_batches_run_step_status",
        "knowledge_import_batches",
        ["run_id", "step", "status"],
    )


def downgrade() -> None:
    op.drop_table("knowledge_import_batches")
