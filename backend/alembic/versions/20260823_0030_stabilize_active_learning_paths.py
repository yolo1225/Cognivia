"""Stabilize active learning path history order.

Revision ID: 20260823_0030
Revises: 20260823_0029
"""

import json
from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "20260823_0030"
down_revision = "20260823_0029"
branch_labels = None
depends_on = None


def _ordered_states(states: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        (state for state in states.values() if isinstance(state, dict)),
        key=lambda state: int(state.get("path_order") or 0),
    )


def _replace_stage_order(payload: dict[str, Any], knowledge_ids: list[str]) -> None:
    stages = [dict(stage) for stage in payload.get("stages") or [] if isinstance(stage, dict)]
    target = next((stage for stage in stages if "knowledge_ids" in stage), None)
    if target is None:
        target = {"name": "学习主线", "description": "持续学习主线"}
        stages.insert(0, target)
    target["knowledge_ids"] = knowledge_ids
    payload["stages"] = stages


def _stabilize(payload: dict[str, Any]) -> tuple[dict[str, Any], str | None, bool]:
    states = payload.get("node_states") or {}
    if not isinstance(states, dict) or not states:
        return payload, None, False
    retired = payload.get("retired_node_states") or {}
    retired = retired if isinstance(retired, dict) else {}
    ordered = _ordered_states(states)
    restored_completed = [
        state
        for state in _ordered_states(retired)
        if state.get("status") == "completed"
        and state.get("knowledge_id") not in {
            item.get("knowledge_id") for item in ordered
        }
    ]
    completed = [
        *[state for state in ordered if state.get("status") == "completed"],
        *restored_completed,
    ]
    preferred_current_id = payload.get("current_node_id")
    current = next(
        (
            state
            for state in ordered
            if state.get("path_node_id") == preferred_current_id
            and state.get("status") != "completed"
        ),
        None,
    )
    if current is None:
        current = next(
            (state for state in ordered if state.get("status") == "current"),
            None,
        )
    future = [
        state
        for state in ordered
        if state.get("status") != "completed" and state is not current
    ]
    if current is None and future:
        current = future.pop(0)
    stable = [*completed, *([current] if current else []), *future]
    next_states: dict[str, dict[str, Any]] = {}
    for index, state in enumerate(stable, start=1):
        item = dict(state)
        item["path_order"] = index
        if item.get("status") != "completed":
            item["status"] = "current" if state is current else "locked"
            item["completed_at"] = None
            item["completion_evidence_ids"] = []
        next_states[str(item["path_node_id"])] = item

    restored_ids = {state.get("path_node_id") for state in restored_completed}
    next_retired = {
        key: value for key, value in retired.items() if key not in restored_ids
    }
    next_payload = dict(payload)
    next_payload["node_states"] = next_states
    next_payload["current_node_id"] = current.get("path_node_id") if current else None
    next_payload["retired_node_states"] = next_retired
    _replace_stage_order(
        next_payload,
        [str(state.get("knowledge_id")) for state in stable if state.get("knowledge_id")],
    )
    path_status = "completed" if stable and current is None else "active"
    return next_payload, path_status, next_payload != payload


def upgrade() -> None:
    connection = op.get_bind()
    rows = list(
        connection.execute(
            sa.text(
                """
                SELECT id, path_json
                FROM learning_paths
                WHERE status = 'active'
                ORDER BY id
                """
            )
        ).mappings()
    )
    for row in rows:
        payload = row["path_json"] or {}
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            continue
        stabilized, path_status, changed = _stabilize(payload)
        if not changed and path_status == "active":
            continue
        connection.execute(
            sa.text(
                """
                UPDATE learning_paths
                SET path_json = :payload, status = :status
                WHERE id = :path_id
                """
            ),
            {
                "payload": json.dumps(stabilized, ensure_ascii=False),
                "status": path_status or "active",
                "path_id": row["id"],
            },
        )


def downgrade() -> None:
    # Restoring a malformed order would make completed history appear after
    # the current node again, so this data repair is intentionally irreversible.
    pass
