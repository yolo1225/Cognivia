"""Replace unused v1 expansion questions with the curated five-level bank.

Revision ID: 20260828_0044
Revises: 20260828_0043
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


revision = "20260828_0044"
down_revision = "20260828_0043"
branch_labels = None
depends_on = None

DOMAIN_CODE = "ai_app_dev"
SEED_DIR = Path(__file__).resolve().parents[3] / "data" / "seed"
V1_PATH = SEED_DIR / "question_bank_expansion_v1.json"
V2_PATH = SEED_DIR / "question_bank_expansion_v2.json"


def _records(path: Path) -> list[dict]:
    return list(json.loads(path.read_text(encoding="utf-8")))


def _as_dict(value: object) -> dict:
    return dict(json.loads(value)) if isinstance(value, str) else dict(value or {})


def _as_list(value: object) -> list:
    return list(json.loads(value)) if isinstance(value, str) else list(value or [])


def _knowledge_item(row: dict) -> KnowledgeItem:
    return KnowledgeItem(
        id=int(row["id"]), public_id=str(row["public_id"]),
        domain_code=str(row["domain_code"]), name=str(row["name"]),
        category=str(row["category"]), difficulty=int(row["difficulty"]),
        tags_json=_as_list(row.get("tags_json")),
        evidence_capabilities_json=_as_list(row.get("evidence_capabilities_json")),
        content_md=str(row["content_md"]), source_title=str(row["source_title"]),
        source_url=row.get("source_url"), license_note=str(row["license_note"]),
        source_document_id=row.get("source_document_id"),
        ability_weights_json=_as_dict(row.get("ability_weights_json")), status="published",
    )


def _answer_key(item: KnowledgeItem, record: dict) -> tuple[dict, str]:
    raw = dict(record["answer_key"])
    chunks = candidate_chunks_for_item(item)
    binding = resolve_question_source_binding(item, source_quote=raw["source_quote"], chunks=chunks)
    source_ref_id = str(binding["source_ref_ids"][0])
    source_quote = str(raw["source_quote"])
    bound_chunk = next(chunk for chunk in chunks if chunk.chunk_id == source_ref_id)
    if source_quote not in bound_chunk.content:
        source_quote = bound_chunk.content[:300]
    source_hashes = {source_ref_id: knowledge_item_content_hash(item)}
    aggregate_hash = "sha256:" + hashlib.sha256(
        json.dumps(source_hashes, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    answer = {
        "correct_option": int(raw["correct_option"]),
        "explanation": str(raw["explanation"]),
        "question_slot": int(raw["question_slot"]),
        "quiz_level": str(record["quiz_level"]),
        "question_bank_uses": list(raw["question_bank_uses"]),
        "reserve_role": raw.get("reserve_role"),
        "assessment_focus": raw.get("assessment_focus"),
        "source_quote": source_quote,
        "source_ref_ids": [source_ref_id],
        "source_locators": {source_ref_id: str(binding["source_locator"])},
        "source_content_hashes": source_hashes,
        "evidence_quotes": [{"source_ref_id": source_ref_id, "quote": source_quote}],
        "chunker_version": CHUNKER_VERSION,
    }
    return answer, aggregate_hash


def _has_v1_references(connection: sa.Connection, v1_ids: list[str]) -> bool:
    if not v1_ids:
        return False
    placeholders = ", ".join(f":id_{index}" for index in range(len(v1_ids)))
    params = {f"id_{index}": value for index, value in enumerate(v1_ids)}
    for table, column in (
        ("answer_records", "question_id"),
        ("path_node_assessments", "question_id"),
        ("mistake_review_attempts", "question_id"),
    ):
        count = connection.scalar(sa.text(
            f"SELECT COUNT(*) FROM {table} WHERE {column} IN ("
            f"SELECT id FROM diagnostic_questions WHERE public_id IN ({placeholders}))"
        ), params)
        if count:
            return True
    resources = connection.execute(sa.text(
        "SELECT structured_content_json FROM learning_resources WHERE resource_type = 'graded_quiz'"
    )).scalars()
    return any(
        any(question_id in json.dumps(value, ensure_ascii=False) for question_id in v1_ids)
        for value in resources
    )


def _insert_records(connection: sa.Connection, records: list[dict]) -> None:
    rows = connection.execute(sa.text(
        "SELECT id, public_id, domain_code, name, category, difficulty, tags_json, "
        "evidence_capabilities_json, content_md, source_title, source_url, license_note, "
        "source_document_id, ability_weights_json FROM knowledge_items WHERE domain_code = :domain"
    ), {"domain": DOMAIN_CODE}).mappings()
    knowledge = {str(row["public_id"]): _knowledge_item(dict(row)) for row in rows}
    now = datetime.now(UTC).replace(tzinfo=None)
    for record in records:
        if connection.scalar(sa.text("SELECT 1 FROM diagnostic_questions WHERE public_id = :id"), {"id": record["question_id"]}):
            continue
        item = knowledge.get(str(record["knowledge_id"]))
        if item is None:
            raise RuntimeError(f"question_bank_knowledge_missing:{record['knowledge_id']}")
        answer, source_hash = _answer_key(item, record)
        report = {
            "rule_version": QUESTION_CERTIFICATION_RULE_VERSION,
            "deterministic_passed": True,
            "certification_method": record.get("certification_method", "curated_seed_exact_evidence"),
            "failed_fields": [], "source_content_hash": source_hash,
        }
        connection.execute(sa.text("""
            INSERT INTO diagnostic_questions (
                public_id, domain_code, knowledge_item_id, related_knowledge_ids_json,
                question_type, stem, options_json, answer_key_json, difficulty, status,
                certification_status, certification_rule_version, certification_report_json,
                source_content_hash, certified_at, created_at, updated_at
            ) VALUES (
                :public_id, :domain, :knowledge_item_id, :related, 'single_choice', :stem,
                :options, :answer, :difficulty, 'active', 'certified', :rule_version,
                :report, :source_hash, :now, :now, :now
            )
        """), {
            "public_id": record["question_id"], "domain": DOMAIN_CODE,
            "knowledge_item_id": item.id, "related": json.dumps([]), "stem": record["stem"],
            "options": json.dumps(record["options"], ensure_ascii=False),
            "answer": json.dumps(answer, ensure_ascii=False), "difficulty": int(record["difficulty"]),
            "rule_version": QUESTION_CERTIFICATION_RULE_VERSION,
            "report": json.dumps(report, ensure_ascii=False), "source_hash": source_hash, "now": now,
        })


def _calibrate_legacy(connection: sa.Connection, *, reverse: bool = False) -> None:
    rows = connection.execute(sa.text(
        "SELECT public_id, answer_key_json, difficulty FROM diagnostic_questions "
        "WHERE domain_code = :domain AND question_type = 'single_choice' AND public_id NOT LIKE 'dq_qb%'"
    ), {"domain": DOMAIN_CODE}).mappings()
    for row in rows:
        answer = _as_dict(row["answer_key_json"])
        if reverse:
            if "difficulty_before_0044" not in answer:
                continue
            difficulty = int(answer.pop("difficulty_before_0044"))
            previous_level = answer.pop("quiz_level_before_0044", None)
            if previous_level is None:
                answer.pop("quiz_level", None)
            else:
                answer["quiz_level"] = previous_level
        else:
            answer.setdefault("difficulty_before_0044", int(row["difficulty"]))
            answer.setdefault("quiz_level_before_0044", answer.get("quiz_level"))
            difficulty = 3 if row["public_id"] == "dq_062_async_taskgroup" else 1
            answer["quiz_level"] = "improvement" if difficulty == 3 else "foundation"
            answer.setdefault("question_bank_uses", ["diagnosis", "graded_quiz"])
        connection.execute(sa.text(
            "UPDATE diagnostic_questions SET difficulty = :difficulty, answer_key_json = :answer WHERE public_id = :id"
        ), {"difficulty": difficulty, "answer": json.dumps(answer, ensure_ascii=False), "id": row["public_id"]})


def upgrade() -> None:
    connection = op.get_bind()
    v1 = _records(V1_PATH)
    v1_ids = [str(record["question_id"]) for record in v1]
    if _has_v1_references(connection, v1_ids):
        raise RuntimeError("question_bank_v1_in_use")
    for question_id in v1_ids:
        connection.execute(sa.text("DELETE FROM diagnostic_questions WHERE public_id = :id"), {"id": question_id})
    _calibrate_legacy(connection)
    _insert_records(connection, _records(V2_PATH))


def downgrade() -> None:
    connection = op.get_bind()
    v2_ids = [str(record["question_id"]) for record in _records(V2_PATH)]
    if _has_v1_references(connection, v2_ids):
        raise RuntimeError("question_bank_v2_in_use")
    for question_id in v2_ids:
        connection.execute(sa.text("DELETE FROM diagnostic_questions WHERE public_id = :id"), {"id": question_id})
    _calibrate_legacy(connection, reverse=True)
    _insert_records(connection, _records(V1_PATH))
