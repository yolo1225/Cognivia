"""Add interaction-driven learning adjustment proposals.

Revision ID: 20260823_0028
Revises: 20260822_0027
"""

from alembic import op
import sqlalchemy as sa


revision = "20260823_0028"
down_revision = "20260822_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "learning_adjustment_proposals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("learner_id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("learning_path_id", sa.Integer(), nullable=False),
        sa.Column("path_node_id", sa.String(length=128), nullable=False),
        sa.Column("tutoring_session_id", sa.Integer(), nullable=False),
        sa.Column("source_resource_id", sa.Integer(), nullable=False),
        sa.Column("hypothesis_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("trigger_source", sa.String(length=32), nullable=False),
        sa.Column("source_feedback_ids_json", sa.JSON(), nullable=False),
        sa.Column("evidence_summary_json", sa.JSON(), nullable=False),
        sa.Column("validation_result_json", sa.JSON(), nullable=False),
        sa.Column("resulting_profile_id", sa.Integer(), nullable=True),
        sa.Column("resulting_learning_path_id", sa.Integer(), nullable=True),
        sa.Column("resource_recommendation_json", sa.JSON(), nullable=False),
        sa.Column("resource_decision", sa.String(length=16), nullable=True),
        sa.Column("generation_task_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["learner_id"], ["learners.id"]),
        sa.ForeignKeyConstraint(["profile_id"], ["learner_profiles.id"]),
        sa.ForeignKeyConstraint(["learning_path_id"], ["learning_paths.id"]),
        sa.ForeignKeyConstraint(["tutoring_session_id"], ["tutoring_sessions.id"]),
        sa.ForeignKeyConstraint(["source_resource_id"], ["learning_resources.id"]),
        sa.ForeignKeyConstraint(["resulting_profile_id"], ["learner_profiles.id"]),
        sa.ForeignKeyConstraint(["resulting_learning_path_id"], ["learning_paths.id"]),
        sa.ForeignKeyConstraint(["generation_task_id"], ["generation_tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, columns, unique in (
        ("ix_learning_adjustment_proposals_public_id", ["public_id"], True),
        ("ix_learning_adjustment_proposals_learner_id", ["learner_id"], False),
        ("ix_learning_adjustment_proposals_profile_id", ["profile_id"], False),
        ("ix_learning_adjustment_proposals_learning_path_id", ["learning_path_id"], False),
        ("ix_learning_adjustment_proposals_path_node_id", ["path_node_id"], False),
        ("ix_learning_adjustment_proposals_tutoring_session_id", ["tutoring_session_id"], False),
        ("ix_learning_adjustment_proposals_hypothesis_type", ["hypothesis_type"], False),
        ("ix_learning_adjustment_proposals_status", ["status"], False),
    ):
        op.create_index(name, "learning_adjustment_proposals", columns, unique=unique)
    op.add_column(
        "path_node_assessments",
        sa.Column("adjustment_proposal_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "path_node_assessments",
        sa.Column("trigger_source", sa.String(length=32), nullable=False, server_default="legacy"),
    )
    op.create_foreign_key(
        "fk_path_node_assessments_adjustment_proposal_id",
        "path_node_assessments",
        "learning_adjustment_proposals",
        ["adjustment_proposal_id"],
        ["id"],
    )
    op.create_index(
        "ix_path_node_assessments_adjustment_proposal_id",
        "path_node_assessments",
        ["adjustment_proposal_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_path_node_assessments_adjustment_proposal_id",
        table_name="path_node_assessments",
    )
    op.drop_constraint(
        "fk_path_node_assessments_adjustment_proposal_id",
        "path_node_assessments",
        type_="foreignkey",
    )
    op.drop_column("path_node_assessments", "trigger_source")
    op.drop_column("path_node_assessments", "adjustment_proposal_id")
    for name in (
        "ix_learning_adjustment_proposals_status",
        "ix_learning_adjustment_proposals_hypothesis_type",
        "ix_learning_adjustment_proposals_tutoring_session_id",
        "ix_learning_adjustment_proposals_path_node_id",
        "ix_learning_adjustment_proposals_learning_path_id",
        "ix_learning_adjustment_proposals_profile_id",
        "ix_learning_adjustment_proposals_learner_id",
        "ix_learning_adjustment_proposals_public_id",
    ):
        op.drop_index(name, table_name="learning_adjustment_proposals")
    op.drop_table("learning_adjustment_proposals")
