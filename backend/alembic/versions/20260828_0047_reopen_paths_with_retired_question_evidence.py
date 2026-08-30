"""Reopen paths completed with retired template-question evidence.

Revision ID: 20260828_0047
Revises: 20260828_0046
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


revision = "20260828_0047"
down_revision = "20260828_0046"
branch_labels = None
depends_on = None


def _as_dict(value: object) -> dict:
    return dict(json.loads(value)) if isinstance(value, str) else dict(value or {})


def _record_ids(values: object) -> set[int]:
    result: set[int] = set()
    for value in values if isinstance(values, list) else []:
        text = str(value)
        if not text.startswith("answer_record:"):
            continue
        try:
            result.add(int(text.split(":", 1)[1]))
        except ValueError:
            continue
    return result


def upgrade() -> None:
    connection = op.get_bind()
    retired_record_ids = {
        int(value)
        for value in connection.execute(sa.text("""
            SELECT a.id
            FROM answer_records a
            JOIN diagnostic_questions q ON q.id = a.question_id
            WHERE q.status = 'disabled'
              AND q.disabled_reason = 'superseded_by_source_grounded_v3_question_bank'
        """)).scalars()
    }
    if not retired_record_ids:
        return
    paths = connection.execute(sa.text("""
        SELECT id, path_json
        FROM learning_paths
        WHERE status = 'active'
    """)).mappings()
    for row in paths:
        payload = _as_dict(row["path_json"])
        states = payload.get("node_states") or {}
        ordered = sorted(
            (
                (str(node_id), node)
                for node_id, node in states.items()
                if isinstance(node, dict)
            ),
            key=lambda pair: int(pair[1].get("path_order") or 0),
        )
        affected_at = next(
            (
                index
                for index, (_node_id, node) in enumerate(ordered)
                if node.get("status") == "completed"
                and _record_ids(node.get("completion_evidence_ids")) & retired_record_ids
            ),
            None,
        )
        if affected_at is None:
            continue
        for index, (node_id, node) in enumerate(ordered):
            if index < affected_at:
                continue
            node["status"] = "current" if index == affected_at else "locked"
            node.pop("completed_at", None)
            node.pop("completion_evidence_ids", None)
            states[node_id] = node
        payload["node_states"] = states
        payload["current_node_id"] = ordered[affected_at][0]
        connection.execute(sa.text("""
            UPDATE learning_paths
            SET path_json = :path_json, needs_refresh = 1
            WHERE id = :id
        """), {"id": row["id"], "path_json": json.dumps(payload, ensure_ascii=False)})


def downgrade() -> None:
    # Reinstating a path would require accepting retired evidence again.
    pass
