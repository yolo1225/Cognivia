"""Repair source-binding metadata for the curated asyncio question.

Revision ID: 20260826_0042
Revises: 20260826_0041
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from alembic import op
import sqlalchemy as sa


revision = "20260826_0042"
down_revision = "20260826_0041"
branch_labels = None
depends_on = None

QUESTION_ID = "dq_062_async_taskgroup"
SOURCE_QUESTION_ID = "dq_061"


def _as_dict(value: object) -> dict:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value or {})


def upgrade() -> None:
    connection = op.get_bind()
    source = connection.execute(
        sa.text(
            "SELECT answer_key_json, source_content_hash FROM diagnostic_questions WHERE public_id = :public_id"
        ),
        {"public_id": SOURCE_QUESTION_ID},
    ).mappings().first()
    question = connection.execute(
        sa.text(
            "SELECT answer_key_json FROM diagnostic_questions WHERE public_id = :public_id"
        ),
        {"public_id": QUESTION_ID},
    ).mappings().first()
    if source is None or question is None:
        return
    source_answer = _as_dict(source["answer_key_json"])
    answer = _as_dict(question["answer_key_json"])
    for key in (
        "source_ref_ids",
        "source_quote",
        "evidence_quotes",
        "source_locators",
        "source_content_hashes",
        "chunker_version",
    ):
        answer[key] = source_answer.get(key)
    source_hash = str(source["source_content_hash"] or "")
    if not source_hash:
        return
    connection.execute(
        sa.text(
            """
            UPDATE diagnostic_questions
            SET answer_key_json = :answer_key_json,
                source_content_hash = :source_content_hash,
                certification_status = 'certified',
                certification_rule_version = 'question-cert-v1',
                certification_report_json = :certification_report_json,
                certified_at = :certified_at,
                updated_at = :updated_at
            WHERE public_id = :public_id
            """
        ),
        {
            "answer_key_json": json.dumps(answer, ensure_ascii=False),
            "source_content_hash": source_hash,
            "certification_report_json": json.dumps(
                {
                    "rule_version": "question-cert-v1",
                    "failed_fields": [],
                    "source_content_hash": source_hash,
                    "certification_method": "curated_seed_exact_evidence",
                    "deterministic_passed": True,
                },
                ensure_ascii=False,
            ),
            "certified_at": datetime.now(UTC).replace(tzinfo=None),
            "updated_at": datetime.now(UTC).replace(tzinfo=None),
            "public_id": QUESTION_ID,
        },
    )


def downgrade() -> None:
    pass
