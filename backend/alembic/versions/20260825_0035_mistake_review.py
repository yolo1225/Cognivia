"""Add mistake review and persisted graded quiz attempts.

Revision ID: 20260825_0035
Revises: 20260824_0034
"""

from alembic import op
import sqlalchemy as sa


revision = "20260825_0035"
down_revision = "20260824_0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mistake_review_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(64), nullable=False),
        sa.Column("learner_id", sa.Integer(), nullable=False),
        sa.Column("domain_code", sa.String(64), nullable=False),
        sa.Column("knowledge_item_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_record_id", sa.String(128), nullable=False),
        sa.Column("source_resource_id", sa.Integer(), nullable=True),
        sa.Column("question_type", sa.String(32), nullable=False),
        sa.Column("difficulty", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("error_summary_json", sa.JSON(), nullable=False),
        sa.Column("latest_attempt_id", sa.Integer(), nullable=True),
        sa.Column("review_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_wrong_at", sa.DateTime(), nullable=True),
        sa.Column("consolidated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["learner_id"], ["learners.id"]),
        sa.ForeignKeyConstraint(["knowledge_item_id"], ["knowledge_items.id"]),
        sa.ForeignKeyConstraint(["source_resource_id"], ["learning_resources.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint("learner_id", "domain_code", "source_type", "source_record_id", name="uq_mistake_review_source"),
    )
    for column in ("public_id", "learner_id", "domain_code", "knowledge_item_id", "source_type", "status"):
        op.create_index(f"ix_mistake_review_items_{column}", "mistake_review_items", [column])

    op.create_table(
        "mistake_review_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(64), nullable=False),
        sa.Column("mistake_item_id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("answer_record_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="created"),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("threshold", sa.Float(), nullable=False, server_default="0.8"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("scoring_method", sa.String(32), nullable=True),
        sa.Column("evidence_ref", sa.String(128), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["mistake_item_id"], ["mistake_review_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["question_id"], ["diagnostic_questions.id"]),
        sa.ForeignKeyConstraint(["answer_record_id"], ["answer_records.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index("ix_mistake_review_attempts_public_id", "mistake_review_attempts", ["public_id"])
    op.create_index("ix_mistake_review_attempts_mistake_item_id", "mistake_review_attempts", ["mistake_item_id"])
    op.create_index("ix_mistake_review_attempts_status", "mistake_review_attempts", ["status"])
    op.create_foreign_key(
        "fk_mistake_review_latest_attempt",
        "mistake_review_items",
        "mistake_review_attempts",
        ["latest_attempt_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "resource_quiz_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(64), nullable=False),
        sa.Column("learner_id", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("resource_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(32), nullable=False, server_default="in_progress"),
        sa.Column("current_question_id", sa.String(128), nullable=True),
        sa.Column("answers_json", sa.JSON(), nullable=False),
        sa.Column("objective_correct", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("objective_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["learner_id"], ["learners.id"]),
        sa.ForeignKeyConstraint(["resource_id"], ["learning_resources.id"]),
        sa.UniqueConstraint("public_id"),
    )
    for column in ("public_id", "learner_id", "resource_id", "status"):
        op.create_index(f"ix_resource_quiz_attempts_{column}", "resource_quiz_attempts", [column])


def downgrade() -> None:
    op.drop_table("resource_quiz_attempts")
    op.drop_constraint("fk_mistake_review_latest_attempt", "mistake_review_items", type_="foreignkey")
    op.drop_table("mistake_review_attempts")
    op.drop_table("mistake_review_items")
