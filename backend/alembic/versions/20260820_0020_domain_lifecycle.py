"""M3 domain lifecycle and readiness defaults.

Revision ID: 20260820_0020
Revises: 20260820_0019
"""

import json

from alembic import op
import sqlalchemy as sa


revision = "20260820_0020"
down_revision = "20260820_0019"
branch_labels = None
depends_on = None


PRIMARY_READINESS_POLICY = {
    "minimum_published_knowledge": 50,
    "minimum_diagnostic_questions": 60,
}
SECONDARY_READINESS_POLICY = {
    "minimum_published_knowledge": 10,
    "minimum_diagnostic_questions": 10,
}


def upgrade() -> None:
    op.add_column(
        "domains",
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
    )
    op.create_index("ix_domains_status", "domains", ["status"], unique=False)
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT domain_code, config_json FROM domains")).mappings()
    for row in rows:
        domain_code = str(row["domain_code"])
        raw_config = row["config_json"]
        config = (
            dict(raw_config or {})
            if isinstance(raw_config, dict)
            else json.loads(raw_config or "{}")
        )
        config["readiness_policy"] = (
            PRIMARY_READINESS_POLICY if domain_code == "ai_app_dev" else SECONDARY_READINESS_POLICY
        )
        bind.execute(
            sa.text(
                "UPDATE domains SET status=:status, config_json=:config WHERE domain_code=:code"
            ),
            {
                "status": "ready" if domain_code == "ai_app_dev" else "preparing",
                "config": json.dumps(config, ensure_ascii=False),
                "code": domain_code,
            },
        )


def downgrade() -> None:
    op.drop_index("ix_domains_status", table_name="domains")
    op.drop_column("domains", "status")
