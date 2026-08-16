"""Add explicit profile provenance."""
from alembic import op
import sqlalchemy as sa

revision = "20260813_0007"
down_revision = "20260812_0006"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("learner_profiles", sa.Column("profile_source", sa.String(32), nullable=False, server_default="default_seed"))
    op.add_column("learner_profiles", sa.Column("diagnosis_completed", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute("UPDATE learner_profiles p SET profile_source='diagnostic', diagnosis_completed=1 WHERE p.decision_reason='diagnostic_result' OR EXISTS (SELECT 1 FROM answer_records a WHERE a.learner_id=p.learner_id)")

def downgrade():
    op.drop_column("learner_profiles", "diagnosis_completed")
    op.drop_column("learner_profiles", "profile_source")
