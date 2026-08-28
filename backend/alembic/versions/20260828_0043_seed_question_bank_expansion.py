"""Seed the static 3+2 ai_app_dev question-bank expansion.

Revision ID: 20260828_0043
Revises: 20260826_0042
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from alembic import op
import sqlalchemy as sa

from app.models import KnowledgeItem
from app.rag.candidate_chunker import CHUNKER_VERSION
from app.services.question_certification_service import (
    QUESTION_CERTIFICATION_RULE_VERSION,
    knowledge_item_content_hash,
)
from app.services.question_source_binding_service import (
    candidate_chunks_for_item,
    resolve_question_source_binding,
)


revision = "20260828_0043"
down_revision = "20260826_0042"
branch_labels = None
depends_on = None

DOMAIN_CODE = "ai_app_dev"
_EXPANSION_PATH = Path(__file__).resolve().parents[3] / "data" / "seed" / "question_bank_expansion_v1.json"


def _records() -> list[dict]:
    if not _EXPANSION_PATH.exists():
        raise RuntimeError(f"question_bank_expansion_missing:{_EXPANSION_PATH}")
    return list(json.loads(_EXPANSION_PATH.read_text(encoding="utf-8")))


def _as_list(value: object) -> list:
    if isinstance(value, str):
        return list(json.loads(value))
    return list(value or [])


def _as_dict(value: object) -> dict:
    if isinstance(value, str):
        return dict(json.loads(value))
    return dict(value or {})


def _knowledge_item(row: dict) -> KnowledgeItem:
    return KnowledgeItem(
        id=int(row["id"]),
        public_id=str(row["public_id"]),
        domain_code=str(row["domain_code"]),
        name=str(row["name"]),
        category=str(row["category"]),
        difficulty=int(row["difficulty"]),
        tags_json=_as_list(row.get("tags_json")),
        evidence_capabilities_json=_as_list(row.get("evidence_capabilities_json")),
        content_md=str(row["content_md"]),
        source_title=str(row["source_title"]),
        source_url=row.get("source_url"),
        license_note=str(row["license_note"]),
        source_document_id=row.get("source_document_id"),
        ability_weights_json=_as_dict(row.get("ability_weights_json")),
        status="published",
    )


def _answer_key(item: KnowledgeItem, record: dict) -> tuple[dict, str]:
    raw = dict(record["answer_key"])
    chunks = candidate_chunks_for_item(item)
    binding = resolve_question_source_binding(
        item, source_quote=raw["source_quote"], chunks=chunks
    )
    source_ref_id = str(binding["source_ref_ids"][0])
    source_hash = knowledge_item_content_hash(item)
    source_hashes = {source_ref_id: source_hash}
    aggregate_hash = "sha256:" + hashlib.sha256(
        json.dumps(source_hashes, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    answer = {
        "correct_option": int(raw["correct_option"]),
        "explanation": str(raw["explanation"]),
        "question_slot": int(raw["question_slot"]),
        "quiz_level": str(record["quiz_level"]),
        "question_bank_uses": list(raw["question_bank_uses"]),
        "source_quote": str(raw["source_quote"]),
        "source_ref_ids": [source_ref_id],
        "source_locators": {source_ref_id: str(binding["source_locator"])},
        "source_content_hashes": source_hashes,
        "evidence_quotes": [
            {"source_ref_id": source_ref_id, "quote": str(raw["source_quote"])}
        ],
        "chunker_version": CHUNKER_VERSION,
    }
    return answer, aggregate_hash


def upgrade() -> None:
    connection = op.get_bind()
    records = _records()
    expansion_ids = {str(record["question_id"]) for record in records}
    legacy_rows = connection.execute(
        sa.text(
            "SELECT public_id, answer_key_json FROM diagnostic_questions "
            "WHERE domain_code = :domain_code"
        ),
        {"domain_code": DOMAIN_CODE},
    ).mappings()
    for row in legacy_rows:
        if str(row["public_id"]) in expansion_ids:
            continue
        answer = _as_dict(row["answer_key_json"])
        if "question_bank_uses" in answer:
            continue
        answer["question_bank_uses_before_0043"] = None
        answer["question_bank_uses"] = ["diagnosis", "graded_quiz"]
        connection.execute(
            sa.text(
                "UPDATE diagnostic_questions SET answer_key_json = :answer_key_json "
                "WHERE public_id = :public_id"
            ),
            {"answer_key_json": json.dumps(answer, ensure_ascii=False), "public_id": row["public_id"]},
        )
    knowledge_rows = connection.execute(
        sa.text(
            "SELECT id, public_id, domain_code, name, category, difficulty, tags_json, "
            "evidence_capabilities_json, content_md, source_title, source_url, license_note, "
            "source_document_id, ability_weights_json FROM knowledge_items "
            "WHERE domain_code = :domain_code"
        ),
        {"domain_code": DOMAIN_CODE},
    ).mappings()
    knowledge_by_id = {str(row["public_id"]): _knowledge_item(dict(row)) for row in knowledge_rows}
    now = datetime.now(UTC).replace(tzinfo=None)
    for record in records:
        question_id = str(record["question_id"])
        if connection.scalar(
            sa.text("SELECT 1 FROM diagnostic_questions WHERE public_id = :public_id"),
            {"public_id": question_id},
        ):
            continue
        item = knowledge_by_id.get(str(record["knowledge_id"]))
        if item is None:
            raise RuntimeError(f"question_bank_knowledge_missing:{record['knowledge_id']}")
        answer, aggregate_hash = _answer_key(item, record)
        report = {
            "rule_version": QUESTION_CERTIFICATION_RULE_VERSION,
            "deterministic_passed": True,
            "certification_method": record.get(
                "certification_method", "curated_seed_exact_evidence"
            ),
            "failed_fields": [],
            "source_content_hash": aggregate_hash,
        }
        connection.execute(
            sa.text(
                """
                INSERT INTO diagnostic_questions (
                    public_id, domain_code, knowledge_item_id, related_knowledge_ids_json,
                    question_type, stem, options_json, answer_key_json, difficulty,
                    status, certification_status, certification_rule_version,
                    certification_report_json, source_content_hash, certified_at,
                    created_at, updated_at
                ) VALUES (
                    :public_id, :domain_code, :knowledge_item_id, :related_knowledge_ids_json,
                    'single_choice', :stem, :options_json, :answer_key_json, :difficulty,
                    'active', 'certified', :certification_rule_version,
                    :certification_report_json, :source_content_hash, :certified_at,
                    :created_at, :updated_at
                )
                """
            ),
            {
                "public_id": question_id,
                "domain_code": DOMAIN_CODE,
                "knowledge_item_id": item.id,
                "related_knowledge_ids_json": json.dumps([]),
                "stem": str(record["stem"]),
                "options_json": json.dumps(record["options"], ensure_ascii=False),
                "answer_key_json": json.dumps(answer, ensure_ascii=False),
                "difficulty": int(record["difficulty"]),
                "certification_rule_version": QUESTION_CERTIFICATION_RULE_VERSION,
                "certification_report_json": json.dumps(report, ensure_ascii=False),
                "source_content_hash": aggregate_hash,
                "certified_at": now,
                "created_at": now,
                "updated_at": now,
            },
        )


def downgrade() -> None:
    connection = op.get_bind()
    for record in _records():
        connection.execute(
            sa.text("DELETE FROM diagnostic_questions WHERE public_id = :public_id"),
            {"public_id": str(record["question_id"])},
        )
    rows = connection.execute(
        sa.text(
            "SELECT public_id, answer_key_json FROM diagnostic_questions "
            "WHERE domain_code = :domain_code"
        ),
        {"domain_code": DOMAIN_CODE},
    ).mappings()
    for row in rows:
        answer = _as_dict(row["answer_key_json"])
        if "question_bank_uses_before_0043" not in answer:
            continue
        previous = answer.pop("question_bank_uses_before_0043")
        if previous is None:
            answer.pop("question_bank_uses", None)
        else:
            answer["question_bank_uses"] = previous
        connection.execute(
            sa.text(
                "UPDATE diagnostic_questions SET answer_key_json = :answer_key_json "
                "WHERE public_id = :public_id"
            ),
            {"answer_key_json": json.dumps(answer, ensure_ascii=False), "public_id": row["public_id"]},
        )
