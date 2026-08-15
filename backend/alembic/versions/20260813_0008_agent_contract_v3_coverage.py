"""add agent contract v3 knowledge coverage persistence

Revision ID: 20260813_0008
Revises: 20260813_0007
"""

from alembic import op
import sqlalchemy as sa

revision = "20260813_0008"
down_revision = "20260813_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("generation_tasks", sa.Column("package_coverage_json", sa.JSON(), nullable=True))
    op.add_column("learning_resources", sa.Column("knowledge_coverage_json", sa.JSON(), nullable=True))
    op.add_column("review_reports", sa.Column("target_knowledge_ids_json", sa.JSON(), nullable=True))
    op.add_column("review_reports", sa.Column("covered_knowledge_ids_json", sa.JSON(), nullable=True))
    op.add_column("review_reports", sa.Column("missing_knowledge_ids_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("review_reports", "missing_knowledge_ids_json")
    op.drop_column("review_reports", "covered_knowledge_ids_json")
    op.drop_column("review_reports", "target_knowledge_ids_json")
    op.drop_column("learning_resources", "knowledge_coverage_json")
    op.drop_column("generation_tasks", "package_coverage_json")
