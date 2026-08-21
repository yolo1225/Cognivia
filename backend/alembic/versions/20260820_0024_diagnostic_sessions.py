"""Add durable asynchronous diagnostic sessions.

Revision ID: 20260820_0024
Revises: 20260820_0023
"""

from alembic import op
import sqlalchemy as sa


revision = "20260820_0024"
down_revision = "20260820_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "diagnostic_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("learner_id", sa.Integer(), nullable=False),
        sa.Column("domain_code", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("question_ids_json", sa.JSON(), nullable=False),
        sa.Column("context_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("selection_summary_json", sa.JSON(), nullable=False),
        sa.Column("answer_hash", sa.String(length=71), nullable=True),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scoring_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("profile_id", sa.Integer(), nullable=True),
        sa.Column("learning_path_id", sa.Integer(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["learner_id"], ["learners.id"]),
        sa.ForeignKeyConstraint(["profile_id"], ["learner_profiles.id"]),
        sa.ForeignKeyConstraint(["learning_path_id"], ["learning_paths.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_diagnostic_sessions_public_id", "diagnostic_sessions", ["public_id"], unique=True
    )
    op.create_index(
        "ix_diagnostic_sessions_learner_id", "diagnostic_sessions", ["learner_id"]
    )
    op.create_index(
        "ix_diagnostic_sessions_domain_code", "diagnostic_sessions", ["domain_code"]
    )
    op.create_index("ix_diagnostic_sessions_status", "diagnostic_sessions", ["status"])
    op.alter_column(
        "answer_records",
        "confidence",
        existing_type=sa.Float(),
        nullable=True,
        existing_server_default="1",
    )
    op.execute(
        "UPDATE answer_records SET confidence = NULL "
        "WHERE scoring_status IN ('pending', 'pending_scoring')"
    )


def downgrade() -> None:
    op.execute("UPDATE answer_records SET confidence = 1 WHERE confidence IS NULL")
    op.alter_column(
        "answer_records",
        "confidence",
        existing_type=sa.Float(),
        nullable=False,
        existing_server_default="1",
    )
    op.drop_index("ix_diagnostic_sessions_status", table_name="diagnostic_sessions")
    op.drop_index("ix_diagnostic_sessions_domain_code", table_name="diagnostic_sessions")
    op.drop_index("ix_diagnostic_sessions_learner_id", table_name="diagnostic_sessions")
    op.drop_index("ix_diagnostic_sessions_public_id", table_name="diagnostic_sessions")
    op.drop_table("diagnostic_sessions")
