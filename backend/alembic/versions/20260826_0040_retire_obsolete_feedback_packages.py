"""Retire feedback packages whose target path node is already completed.

Revision ID: 20260826_0040
Revises: 20260826_0039
"""

from __future__ import annotations

import json
from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "20260826_0040"
down_revision = "20260826_0039"
branch_labels = None
depends_on = None


def _targets_completed_node(payload: dict[str, Any], node_id: str | None) -> bool:
    if not node_id:
        return False
    states = payload.get("node_states") or {}
    state = states.get(node_id) if isinstance(states, dict) else None
    return isinstance(state, dict) and state.get("status") == "completed"


def upgrade() -> None:
    connection = op.get_bind()
    rows = list(
        connection.execute(
            sa.text(
                """
                SELECT task.id, task.path_node_id, path.path_json
                FROM generation_tasks AS task
                JOIN learning_paths AS path ON path.id = task.learning_path_id
                WHERE task.event_type = 'resource_feedback'
                  AND task.is_current_package = 1
                  AND task.path_node_id IS NOT NULL
                """
            )
        ).mappings()
    )
    obsolete_task_ids: list[int] = []
    for row in rows:
        payload = row["path_json"] or {}
        if isinstance(payload, str):
            payload = json.loads(payload)
        if isinstance(payload, dict) and _targets_completed_node(payload, row["path_node_id"]):
            obsolete_task_ids.append(int(row["id"]))

    for task_id in obsolete_task_ids:
        connection.execute(
            sa.text(
                "UPDATE generation_tasks SET is_current_package = 0 WHERE id = :task_id"
            ),
            {"task_id": task_id},
        )
        connection.execute(
            sa.text(
                "UPDATE learning_resources SET is_current = 0 WHERE generation_task_id = :task_id"
            ),
            {"task_id": task_id},
        )
        connection.execute(
            sa.text(
                """
                UPDATE learning_package_resources
                SET freshness_status = 'superseded'
                WHERE package_task_id = :task_id AND freshness_status = 'current'
                """
            ),
            {"task_id": task_id},
        )


def downgrade() -> None:
    pass
