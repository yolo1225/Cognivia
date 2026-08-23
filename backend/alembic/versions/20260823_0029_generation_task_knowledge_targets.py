"""Add explicit generation task knowledge targets.

Revision ID: 20260823_0029
Revises: 20260823_0028
"""

from alembic import op
import sqlalchemy as sa


revision = "20260823_0029"
down_revision = "20260823_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "generation_tasks",
        sa.Column(
            "resource_knowledge_targets_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("('{}')"),
        ),
    )


def downgrade() -> None:
    op.drop_column("generation_tasks", "resource_knowledge_targets_json")
