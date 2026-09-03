"""Repair v2 question quotes that crossed a candidate-chunk boundary.

Revision ID: 20260828_0045
Revises: 20260828_0044
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa

from app.models import KnowledgeItem
from app.alembic_legacy_question_helpers import candidate_chunks_for_item


revision = "20260828_0045"
down_revision = "20260828_0044"
branch_labels = None
depends_on = None


def _as_dict(value: object) -> dict:
    return dict(json.loads(value)) if isinstance(value, str) else dict(value or {})


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(sa.text("""
        SELECT q.public_id, q.answer_key_json, k.id, k.public_id AS knowledge_public_id,
               k.domain_code, k.name, k.category, k.difficulty, k.tags_json,
               k.evidence_capabilities_json, k.content_md, k.source_title, k.source_url,
               k.license_note, k.source_document_id, k.ability_weights_json
        FROM diagnostic_questions q
        JOIN knowledge_items k ON k.id = q.knowledge_item_id
        WHERE q.public_id LIKE 'dq_qb_%'
    """)).mappings()
    for row in rows:
        answer = _as_dict(row["answer_key_json"])
        if not answer.get("reserve_role") and not answer.get("assessment_focus"):
            continue
        item = KnowledgeItem(
            id=int(row["id"]), public_id=str(row["knowledge_public_id"]),
            domain_code=str(row["domain_code"]), name=str(row["name"]),
            category=str(row["category"]), difficulty=int(row["difficulty"]),
            tags_json=_as_dict(row["tags_json"]) if isinstance(row["tags_json"], dict) else list(json.loads(row["tags_json"]) if isinstance(row["tags_json"], str) else row["tags_json"] or []),
            evidence_capabilities_json=list(json.loads(row["evidence_capabilities_json"]) if isinstance(row["evidence_capabilities_json"], str) else row["evidence_capabilities_json"] or []),
            content_md=str(row["content_md"]), source_title=str(row["source_title"]),
            source_url=row["source_url"], license_note=str(row["license_note"]),
            source_document_id=row["source_document_id"],
            ability_weights_json=_as_dict(row["ability_weights_json"]), status="published",
        )
        source_ref_id = str((answer.get("source_ref_ids") or [""])[0])
        chunk = next((value for value in candidate_chunks_for_item(item) if value.chunk_id == source_ref_id), None)
        if chunk is None:
            continue
        quote = str(answer.get("source_quote") or "")
        if quote in chunk.content:
            continue
        quote = chunk.content[:300]
        answer["source_quote"] = quote
        answer["evidence_quotes"] = [{"source_ref_id": source_ref_id, "quote": quote}]
        connection.execute(sa.text(
            "UPDATE diagnostic_questions SET answer_key_json = :answer WHERE public_id = :id"
        ), {"answer": json.dumps(answer, ensure_ascii=False), "id": row["public_id"]})


def downgrade() -> None:
    pass
