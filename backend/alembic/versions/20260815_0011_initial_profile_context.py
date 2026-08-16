"""Add persisted learner context for initial profile onboarding.

Revision ID: 20260815_0011
Revises: 20260815_0010
"""

from alembic import op
import sqlalchemy as sa


revision = "20260815_0011"
down_revision = "20260815_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("learners", sa.Column("education_level", sa.String(64), nullable=False, server_default=""))
    op.add_column("learners", sa.Column("major", sa.String(128), nullable=False, server_default=""))
    op.add_column("learners", sa.Column("direction_tags_json", sa.JSON(), nullable=False, server_default=sa.text("(JSON_ARRAY())")))
    op.add_column("learner_profiles", sa.Column("context_snapshot_json", sa.JSON(), nullable=False, server_default=sa.text("(JSON_OBJECT())")))
    op.execute("UPDATE learners SET major=background WHERE major='' AND background<>''")


def downgrade() -> None:
    op.drop_column("learner_profiles", "context_snapshot_json")
    op.drop_column("learners", "direction_tags_json")
    op.drop_column("learners", "major")
    op.drop_column("learners", "education_level")
