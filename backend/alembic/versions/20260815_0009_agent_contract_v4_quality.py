"""Agent Contract V4 resource quality metrics.

Revision ID: 20260815_0009
Revises: 20260813_0008
"""

from alembic import op
import sqlalchemy as sa


revision = "20260815_0009"
down_revision = "20260813_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    generation_columns = {item["name"] for item in sa.inspect(bind).get_columns("generation_tasks")}
    if "package_quality_json" not in generation_columns:
        op.add_column("generation_tasks", sa.Column("package_quality_json", sa.JSON(), nullable=False, server_default=sa.text("('{}')")))
    if "failure_reason" not in generation_columns:
        op.add_column("generation_tasks", sa.Column("failure_reason", sa.Text(), nullable=True))
        op.execute("UPDATE generation_tasks SET failure_reason='' WHERE failure_reason IS NULL")
        op.alter_column("generation_tasks", "failure_reason", existing_type=sa.Text(), nullable=False)

    report_columns = {item["name"] for item in sa.inspect(bind).get_columns("review_reports")}
    columns = (
        sa.Column("verifiable_claim_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hallucinated_claim_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hallucination_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("covered_core_knowledge_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("target_core_knowledge_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("core_knowledge_coverage", sa.Float(), nullable=False, server_default="0"),
        sa.Column("quality_passed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("revision_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("model_role_version", sa.String(32), nullable=False, server_default="review-v4"),
    )
    for column in columns:
        if column.name not in report_columns:
            op.add_column("review_reports", column)
    op.execute("UPDATE generation_tasks SET status='failed', decision='failed', failure_reason='legacy_manual_review_retired' WHERE status='waiting_human' OR decision='manual_review_required'")
    op.execute("UPDATE learning_resources SET is_current=0 WHERE review_status='manual_review_required'")


def downgrade() -> None:
    for column in (
        "model_role_version", "revision_count", "quality_passed",
        "core_knowledge_coverage", "target_core_knowledge_count",
        "covered_core_knowledge_count", "hallucination_rate",
        "hallucinated_claim_count", "verifiable_claim_count",
    ):
        op.drop_column("review_reports", column)
    op.drop_column("generation_tasks", "failure_reason")
    op.drop_column("generation_tasks", "package_quality_json")
