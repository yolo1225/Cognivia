"""Aggregate tutoring evidence at the current path node.

Revision ID: 20260823_0031
Revises: 20260823_0030
"""

from alembic import op
import sqlalchemy as sa


revision = "20260823_0031"
down_revision = "20260823_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "resource_feedback",
        sa.Column(
            "evidence_status",
            sa.String(length=32),
            nullable=False,
            server_default="supporting_only",
        ),
    )
    op.add_column(
        "resource_feedback",
        sa.Column("adjustment_proposal_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_resource_feedback_adjustment_proposal_id",
        "resource_feedback",
        "learning_adjustment_proposals",
        ["adjustment_proposal_id"],
        ["id"],
    )
    op.create_index(
        "ix_resource_feedback_evidence_status",
        "resource_feedback",
        ["evidence_status"],
    )
    op.create_index(
        "ix_resource_feedback_adjustment_proposal_id",
        "resource_feedback",
        ["adjustment_proposal_id"],
    )
    op.create_index(
        "ix_resource_feedback_node_evidence_lookup",
        "resource_feedback",
        ["learner_id", "evidence_status", "tutoring_session_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_resource_feedback_node_evidence_lookup", table_name="resource_feedback"
    )
    op.drop_index(
        "ix_resource_feedback_adjustment_proposal_id", table_name="resource_feedback"
    )
    op.drop_index("ix_resource_feedback_evidence_status", table_name="resource_feedback")
    op.drop_constraint(
        "fk_resource_feedback_adjustment_proposal_id",
        "resource_feedback",
        type_="foreignkey",
    )
    op.drop_column("resource_feedback", "adjustment_proposal_id")
    op.drop_column("resource_feedback", "evidence_status")
