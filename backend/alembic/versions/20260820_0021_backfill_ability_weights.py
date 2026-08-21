"""Backfill weights for knowledge imported before M2 runtime governance.

Revision ID: 20260820_0021
Revises: 20260820_0020
"""

import json

from alembic import op
import sqlalchemy as sa


revision = "20260820_0021"
down_revision = "20260820_0020"
branch_labels = None
depends_on = None


BALANCED_WEIGHTS = {
    "theory": 0.3,
    "practice": 0.25,
    "problem_solving": 0.2,
    "knowledge_breadth": 0.25,
    "learning_speed": 0.0,
}


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, ability_weights_json FROM knowledge_items")).mappings()
    for row in rows:
        raw = row["ability_weights_json"]
        weights = dict(raw or {}) if isinstance(raw, dict) else json.loads(raw or "{}")
        if not weights:
            bind.execute(
                sa.text("UPDATE knowledge_items SET ability_weights_json=:weights WHERE id=:id"),
                {"weights": json.dumps(BALANCED_WEIGHTS), "id": row["id"]},
            )


def downgrade() -> None:
    # The previous empty value cannot be distinguished from legitimate balanced weights.
    pass
