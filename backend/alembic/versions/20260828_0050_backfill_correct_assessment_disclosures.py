"""Backfill answer disclosures for correct historical tutoring assessments.

Revision ID: 20260828_0050
Revises: 20260828_0049
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


revision = "20260828_0050"
down_revision = "20260828_0049"
branch_labels = None
depends_on = None


def _as_dict(value: object) -> dict:
    return dict(json.loads(value)) if isinstance(value, str) else dict(value or {})


def _as_list(value: object) -> list:
    return list(json.loads(value)) if isinstance(value, str) else list(value or [])


def _with_correct_disclosure(
    result_value: object, options_value: object, answer_key_value: object
) -> tuple[dict, bool]:
    result = _as_dict(result_value)
    if result.get("is_correct") is not True:
        return result, False
    options = _as_list(options_value)
    answer_key = _as_dict(answer_key_value)
    try:
        correct_option = int(answer_key["correct_option"])
        correct_answer = str(options[correct_option])
    except (KeyError, TypeError, ValueError, IndexError):
        return result, False
    disclosure = {
        "correct_option": correct_option,
        "correct_answer": correct_answer,
        "explanation": str(answer_key.get("explanation") or ""),
    }
    changed = any(result.get(key) != value for key, value in disclosure.items())
    result.update(disclosure)
    return result, changed


def upgrade() -> None:
    connection = op.get_bind()
    assessments = connection.execute(sa.text("""
        SELECT assessment.id, assessment.public_id, assessment.adjustment_proposal_id,
               assessment.result_json, question.options_json, question.answer_key_json
        FROM path_node_assessments AS assessment
        JOIN diagnostic_questions AS question ON question.id = assessment.question_id
        WHERE assessment.status = 'scored'
    """)).mappings()
    result_by_assessment_id: dict[str, dict] = {}
    for row in assessments:
        result, changed = _with_correct_disclosure(
            row["result_json"], row["options_json"], row["answer_key_json"]
        )
        if result.get("is_correct") is not True:
            continue
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
    # Correct-answer disclosures are retained with the scored assessment.
    pass
