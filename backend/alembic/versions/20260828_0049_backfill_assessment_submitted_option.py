"""Backfill learner selections for historical tutoring assessments.

Revision ID: 20260828_0049
Revises: 20260828_0048
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


revision = "20260828_0049"
down_revision = "20260828_0048"
branch_labels = None
depends_on = None

DISCLOSURE_KEYS = {"correct_option", "correct_answer", "explanation"}


def _as_dict(value: object) -> dict:
    return dict(json.loads(value)) if isinstance(value, str) else dict(value or {})


def _with_submitted_option(value: object, answer_text: object) -> tuple[dict, bool]:
    payload = _as_dict(value)
    changed = False
    if payload.get("is_correct") is False:
        for key in DISCLOSURE_KEYS:
            if key in payload:
                payload.pop(key, None)
                changed = True
    if "submitted_option" in payload:
        return payload, changed
    try:
        submitted_option = int(str(answer_text))
    except (TypeError, ValueError):
        return payload, changed
    payload["submitted_option"] = submitted_option
    return payload, True


def upgrade() -> None:
    connection = op.get_bind()
    assessments = connection.execute(sa.text("""
        SELECT assessment.id, assessment.public_id, assessment.adjustment_proposal_id,
               assessment.result_json, record.answer_text
        FROM path_node_assessments AS assessment
        JOIN answer_records AS record ON record.id = assessment.answer_record_id
        WHERE assessment.status = 'scored'
    """)).mappings()
    result_by_assessment_id: dict[str, dict] = {}
    for row in assessments:
        result, changed = _with_submitted_option(row["result_json"], row["answer_text"])
        result_by_assessment_id[str(row["public_id"])] = result
        if changed:
            connection.execute(sa.text("""
                UPDATE path_node_assessments
                SET result_json = :result
                WHERE id = :id
            """), {"id": row["id"], "result": json.dumps(result, ensure_ascii=False)})
        if row["adjustment_proposal_id"] is not None:
            connection.execute(sa.text("""
                UPDATE learning_adjustment_proposals
                SET validation_result_json = :result
                WHERE id = :id
            """), {
                "id": row["adjustment_proposal_id"],
                "result": json.dumps(result, ensure_ascii=False),
            })

    messages = connection.execute(sa.text("""
        SELECT id, metadata_json FROM tutoring_messages
    """)).mappings()
    for row in messages:
        metadata = _as_dict(row["metadata_json"])
        assessment = metadata.get("assessment")
        if not isinstance(assessment, dict):
            continue
        result = result_by_assessment_id.get(str(assessment.get("assessment_id") or ""))
        if result is None:
            continue
        merged = {**assessment, **result}
        if merged == assessment:
            continue
        metadata["assessment"] = merged
        connection.execute(sa.text("""
            UPDATE tutoring_messages
            SET metadata_json = :metadata
            WHERE id = :id
        """), {"id": row["id"], "metadata": json.dumps(metadata, ensure_ascii=False)})


def downgrade() -> None:
    # Historical learner selections are retained for auditability.
    pass
