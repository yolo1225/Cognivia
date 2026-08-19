"""Agent Contract V6 quality semantics and evidence capabilities.

Revision ID: 20260818_0016
Revises: 20260817_0015
"""

from alembic import op
import sqlalchemy as sa


revision = "20260818_0016"
down_revision = "20260817_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_items",
        sa.Column("evidence_capabilities_json", sa.JSON(), nullable=False, server_default=sa.text("('[]')")),
    )
    op.add_column(
        "review_reports",
        sa.Column(
            "quality_rule_version",
            sa.String(length=32),
            nullable=False,
            server_default="quality-v6-20260818",
        ),
    )
    for name in (
        "evaluated_claim_count",
        "contradicted_claim_count",
        "evidence_insufficient_claim_count",
        "unresolved_claim_count",
    ):
        op.add_column(
            "review_reports",
            sa.Column(name, sa.Integer(), nullable=False, server_default="0"),
        )
    op.execute(
        "UPDATE review_reports SET evaluated_claim_count=verifiable_claim_count, "
        "contradicted_claim_count=hallucinated_claim_count, "
        "quality_rule_version='legacy-v5-read-only'"
    )


def downgrade() -> None:
    for name in (
        "unresolved_claim_count",
        "evidence_insufficient_claim_count",
        "contradicted_claim_count",
        "evaluated_claim_count",
        "quality_rule_version",
    ):
        op.drop_column("review_reports", name)
    op.drop_column("knowledge_items", "evidence_capabilities_json")
