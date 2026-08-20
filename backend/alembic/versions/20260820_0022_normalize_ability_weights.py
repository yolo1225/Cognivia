"""Normalize legacy knowledge ability weights to the five runtime dimensions.

Revision ID: 20260820_0022
Revises: 20260820_0021
"""

import json

from alembic import op
import sqlalchemy as sa


revision = "20260820_0022"
down_revision = "20260820_0021"
branch_labels = None
depends_on = None


ABILITY_DIMENSIONS = {
    "theory",
    "practice",
    "problem_solving",
    "knowledge_breadth",
    "learning_speed",
}
BALANCED_WEIGHTS = {
    "theory": 0.3,
    "practice": 0.25,
    "problem_solving": 0.2,
    "knowledge_breadth": 0.25,
    "learning_speed": 0.0,
}


def _valid_weights(weights: dict) -> bool:
    if set(weights) != ABILITY_DIMENSIONS:
        return False
    try:
        values = [float(weights[key]) for key in ABILITY_DIMENSIONS]
    except (TypeError, ValueError):
        return False
    return all(value >= 0 for value in values) and abs(sum(values) - 1.0) <= 1e-9


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, ability_weights_json FROM knowledge_items")).mappings()
    for row in rows:
        raw = row["ability_weights_json"]
        weights = dict(raw or {}) if isinstance(raw, dict) else json.loads(raw or "{}")
        if not _valid_weights(weights):
            bind.execute(
                sa.text("UPDATE knowledge_items SET ability_weights_json=:weights WHERE id=:id"),
                {"weights": json.dumps(BALANCED_WEIGHTS), "id": row["id"]},
            )


def downgrade() -> None:
    # Invalid historical values cannot be reconstructed after normalization.
    pass
