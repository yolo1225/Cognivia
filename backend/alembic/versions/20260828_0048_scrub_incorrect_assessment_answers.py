"""Do not retain answer disclosures for failed tutoring assessments.

Revision ID: 20260828_0048
Revises: 20260828_0047
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


revision = "20260828_0048"
down_revision = "20260828_0047"
branch_labels = None
depends_on = None

DISCLOSURE_KEYS = {"correct_option", "correct_answer", "explanation"}


def _as_dict(value: object) -> dict:
    return dict(json.loads(value)) if isinstance(value, str) else dict(value or {})


def _scrub_result(value: object) -> tuple[dict, bool]:
    payload = _as_dict(value)
    if payload.get("is_correct") is not False:
        return payload, False
    changed = any(key in payload for key in DISCLOSURE_KEYS)
    for key in DISCLOSURE_KEYS:
        payload.pop(key, None)
    return payload, changed


def upgrade() -> None:
    connection = op.get_bind()
    assessments = connection.execute(sa.text("""
        SELECT id, adjustment_proposal_id, result_json
        FROM path_node_assessments
        WHERE status = 'scored'
    """)).mappings()
    changed_proposals: dict[int, dict] = {}
    for row in assessments:
        result, changed = _scrub_result(row["result_json"])
        if not changed:
            continue
        connection.execute(sa.text("""
            UPDATE path_node_assessments SET result_json = :result WHERE id = :id
        """), {"id": row["id"], "result": json.dumps(result, ensure_ascii=False)})
        if row["adjustment_proposal_id"] is not None:
            changed_proposals[int(row["adjustment_proposal_id"])] = result
    for proposal_id, result in changed_proposals.items():
        connection.execute(sa.text("""
            UPDATE learning_adjustment_proposals
            SET validation_result_json = :result WHERE id = :id
        """), {"id": proposal_id, "result": json.dumps(result, ensure_ascii=False)})

    messages = connection.execute(sa.text("""
        SELECT id, metadata_json FROM tutoring_messages
    """)).mappings()
    for row in messages:
        metadata = _as_dict(row["metadata_json"])
        assessment = metadata.get("assessment")
        if not isinstance(assessment, dict):
            continue
        cleaned, changed = _scrub_result(assessment)
        if not changed:
            continue
        metadata["assessment"] = cleaned
        connection.execute(sa.text("""
            UPDATE tutoring_messages SET metadata_json = :metadata WHERE id = :id
        """), {"id": row["id"], "metadata": json.dumps(metadata, ensure_ascii=False)})


def downgrade() -> None:
    # Answer disclosures removed for a failed assessment must not be restored.
    pass
