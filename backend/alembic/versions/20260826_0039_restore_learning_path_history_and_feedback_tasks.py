"""Restore completed path history and feedback-driven task provenance.

Revision ID: 20260826_0039
Revises: 20260826_0038
"""

from __future__ import annotations

import json
from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "20260826_0039"
down_revision = "20260826_0038"
branch_labels = None
depends_on = None


def _states(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for key in ("node_states", "retired_node_states"):
        raw = payload.get(key) or {}
        if isinstance(raw, dict):
            result.extend(item for item in raw.values() if isinstance(item, dict))
    return result


def _node_knowledge_ids(state: dict[str, Any]) -> list[str]:
    return [
        str(value)
        for value in state.get("knowledge_ids") or [state.get("knowledge_id")]
        if value
    ]


def _repair_path(
    payload: dict[str, Any], history_payloads: list[dict[str, Any]]
) -> tuple[dict[str, Any], bool]:
    active_states = [
        item
        for item in (payload.get("node_states") or {}).values()
        if isinstance(item, dict)
    ]
    completed_by_key: dict[tuple[tuple[str, ...], tuple[str, ...]], dict[str, Any]] = {}
    for source in [*history_payloads, payload]:
        for state in _states(source):
            if state.get("status") != "completed":
                continue
            knowledge_ids = tuple(_node_knowledge_ids(state))
            if not knowledge_ids:
                continue
            evidence_ids = tuple(str(value) for value in state.get("completion_evidence_ids") or [])
            key = (knowledge_ids, evidence_ids)
            existing = completed_by_key.get(key)
            if existing is None or str(state.get("completed_at") or "") < str(existing.get("completed_at") or ""):
                completed_by_key[key] = dict(state)
    completed = sorted(
        completed_by_key.values(),
        key=lambda item: (str(item.get("completed_at") or ""), int(item.get("path_order") or 0)),
    )
    completed_node_ids = {str(item.get("path_node_id") or "") for item in completed}
    current = next(
        (
            item
            for item in active_states
            if item.get("status") == "current"
            and str(item.get("path_node_id") or "") not in completed_node_ids
        ),
        None,
    )
    future = [
        item
        for item in active_states
        if item.get("status") != "completed"
        and item is not current
        and str(item.get("path_node_id") or "") not in completed_node_ids
    ]
    if current is None and future:
        current = future.pop(0)
    stable = [*completed, *([current] if current else []), *future]
    next_states: dict[str, dict[str, Any]] = {}
    for order, source in enumerate(stable, start=1):
        state = dict(source)
        node_id = str(state.get("path_node_id") or "")
        if not node_id:
            continue
        state["path_order"] = order
        if state.get("status") != "completed":
            state["status"] = "current" if source is current else "locked"
            state["completed_at"] = None
            state["completion_evidence_ids"] = []
        next_states[node_id] = state
    repaired = dict(payload)
    repaired["node_states"] = next_states
    repaired["current_node_id"] = current.get("path_node_id") if current else None
    retired = payload.get("retired_node_states") or {}
    repaired["retired_node_states"] = {
        key: value
        for key, value in retired.items()
        if key not in next_states and isinstance(value, dict) and value.get("status") != "completed"
    }
    stages = [dict(stage) for stage in repaired.get("stages") or [] if isinstance(stage, dict)]
    primary = next((stage for stage in stages if "knowledge_ids" in stage), None)
    if primary is not None:
        primary["knowledge_ids"] = [
            knowledge_id
            for state in next_states.values()
            for knowledge_id in _node_knowledge_ids(state)
        ]
    repaired["stages"] = stages
    return repaired, repaired != payload


def upgrade() -> None:
    connection = op.get_bind()
    active_rows = list(
        connection.execute(
            sa.text(
                "SELECT id, learner_id, domain_code, path_json FROM learning_paths WHERE status = 'active'"
            )
        ).mappings()
    )
    for row in active_rows:
        payload = row["path_json"] or {}
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            continue
        history_rows = list(
            connection.execute(
                sa.text(
                    """
                    SELECT path_json FROM learning_paths
                    WHERE learner_id = :learner_id AND domain_code = :domain_code AND id != :path_id
                    """
                ),
                {"learner_id": row["learner_id"], "domain_code": row["domain_code"], "path_id": row["id"]},
            ).mappings()
        )
        histories = []
        for item in history_rows:
            history = item["path_json"] or {}
            if isinstance(history, str):
                history = json.loads(history)
            if isinstance(history, dict):
                histories.append(history)
        repaired, changed = _repair_path(payload, histories)
        if changed:
            connection.execute(
                sa.text("UPDATE learning_paths SET path_json = :payload WHERE id = :path_id"),
                {"payload": json.dumps(repaired, ensure_ascii=False), "path_id": row["id"]},
            )

    task_rows = list(
        connection.execute(
            sa.text(
                """
                SELECT proposal.generation_task_id, proposal.source_resource_id,
                       proposal.source_feedback_ids_json, source_resource.generation_task_id AS source_task_id
                FROM learning_adjustment_proposals AS proposal
                JOIN generation_tasks AS task ON task.id = proposal.generation_task_id
                JOIN learning_resources AS source_resource ON source_resource.id = proposal.source_resource_id
                WHERE proposal.generation_task_id IS NOT NULL
                  AND task.trigger_type = 'initial_generation'
                  AND task.event_type = 'generation'
                """
            )
        ).mappings()
    )
    for row in task_rows:
        raw_ids = row["source_feedback_ids_json"] or []
        if isinstance(raw_ids, str):
            raw_ids = json.loads(raw_ids)
        feedback_id = int(raw_ids[-1]) if isinstance(raw_ids, list) and raw_ids else None
        if feedback_id is None:
            continue
        connection.execute(
            sa.text(
                """
                UPDATE generation_tasks
                SET trigger_type = 'resource_feedback', event_type = 'resource_feedback',
                    source_resource_id = :resource_id, source_feedback_id = :feedback_id,
                    source_task_id = COALESCE(source_task_id, :source_task_id)
                WHERE id = :task_id
                """
            ),
            {
                "resource_id": row["source_resource_id"],
                "feedback_id": feedback_id,
                "source_task_id": row["source_task_id"],
                "task_id": row["generation_task_id"],
            },
        )


def downgrade() -> None:
    pass
