"""remove retired manual review persistence

Revision ID: 20260815_0010
Revises: 20260815_0009
"""

from alembic import op
import sqlalchemy as sa


revision = "20260815_0010"
down_revision = "20260815_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    task_columns = {item["name"] for item in inspector.get_columns("generation_tasks")}
    if {"status", "decision", "failure_reason"}.issubset(task_columns):
        op.execute(
            "UPDATE generation_tasks "
            "SET status='failed', decision='failed', failure_reason='legacy_manual_review_removed' "
            "WHERE status='waiting_human' OR decision='manual_review_required'"
        )

    tables = set(inspector.get_table_names())
    if "manual_review_tasks" in tables:
        op.execute("DELETE FROM manual_review_tasks")
        op.drop_table("manual_review_tasks")

    report_columns = {item["name"] for item in inspector.get_columns("review_reports")}
    if "manual_review_required" in report_columns:
        op.drop_column("review_reports", "manual_review_required")


def downgrade() -> None:
    raise NotImplementedError("manual review data is intentionally removed")
