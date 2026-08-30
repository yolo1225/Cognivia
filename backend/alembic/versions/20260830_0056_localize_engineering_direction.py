"""Localize the AI application engineering direction label.

Revision ID: 20260830_0056
Revises: 20260830_0055
"""

import json

from alembic import op
import sqlalchemy as sa


revision = "20260830_0056"
down_revision = "20260830_0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    row = bind.execute(
        sa.text("SELECT id, config_json FROM domains WHERE domain_code = 'ai_app_dev'")
    ).mappings().first()
    if row is None:
        return
    config = row["config_json"]
    if isinstance(config, str):
        config = json.loads(config)
    config = dict(config or {})
    directions = list(config.get("learning_directions") or [])
    changed = False
    for direction in directions:
        if direction.get("value") != "application_engineering":
            continue
        direction["label"] = "AI 应用工程基础"
        direction["description"] = "服务开发、数据、部署、测试与可观测性"
        changed = True
    if changed:
        bind.execute(
            sa.text("UPDATE domains SET config_json = :config WHERE id = :id"),
            {"id": row["id"], "config": json.dumps(config, ensure_ascii=False)},
        )


def downgrade() -> None:
    pass
