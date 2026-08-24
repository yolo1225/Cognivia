"""Attach each legacy current package to its active path node.

Revision ID: 20260822_0027
Revises: 20260822_0026
"""

import json

from alembic import op
import sqlalchemy as sa


revision = "20260822_0027"
down_revision = "20260822_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    paths = connection.execute(
        sa.text(
            """
            SELECT id, learner_id, profile_id, domain_code, path_json
            FROM learning_paths
            WHERE status = 'active'
            ORDER BY created_at DESC, id DESC
            """
        )
    )
    adopted_learners: set[tuple[int, str]] = set()
    for path in paths.mappings():
        key = (path["learner_id"], path["domain_code"])
        if key in adopted_learners:
            continue
        payload = path["path_json"] or {}
        if isinstance(payload, str):
            payload = json.loads(payload)
        current_node_id = payload.get("current_node_id") if isinstance(payload, dict) else None
        if not current_node_id:
            continue
        task_id = connection.scalar(
            sa.text(
                """
                SELECT id
                FROM generation_tasks
                WHERE learner_id = :learner_id
                  AND profile_id = :profile_id
                  AND domain_code = :domain_code
                  AND status = 'completed'
                  AND is_current_package = true
                  AND learning_path_id IS NULL
                  AND path_node_id IS NULL
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """
            ),
            {
                "learner_id": path["learner_id"],
                "profile_id": path["profile_id"],
                "domain_code": path["domain_code"],
            },
        )
        if task_id is None:
            continue
        connection.execute(
            sa.text(
                """
                UPDATE generation_tasks
                SET learning_path_id = :path_id, path_node_id = :path_node_id
                WHERE id = :task_id
                """
            ),
            {
                "path_id": path["id"],
                "path_node_id": current_node_id,
                "task_id": task_id,
            },
        )
        adopted_learners.add(key)


def downgrade() -> None:
    # The backfill has no durable marker, so clearing bindings here could
    # remove bindings created by learners after the upgrade.
    pass
