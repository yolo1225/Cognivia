"""Add production Prompt and contract provenance to Agent runs.

Revision ID: 20260820_0023
Revises: 20260820_0022
"""

from alembic import op
import sqlalchemy as sa


revision = "20260820_0023"
down_revision = "20260820_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("prompt_hash", sa.String(length=64), nullable=False, server_default="unknown"),
    )
    op.add_column(
        "learners",
        sa.Column("is_evaluation", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_learners_is_evaluation", "learners", ["is_evaluation"])
    op.add_column(
        "agent_runs",
        sa.Column(
            "contract_version", sa.String(length=32), nullable=False, server_default="unknown"
        ),
    )


def downgrade() -> None:
    op.drop_index("ix_learners_is_evaluation", table_name="learners")
    op.drop_column("learners", "is_evaluation")
    op.drop_column("agent_runs", "contract_version")
    op.drop_column("agent_runs", "prompt_hash")
