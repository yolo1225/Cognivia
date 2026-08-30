from __future__ import annotations

import argparse
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import DiagnosticQuestion, KnowledgeItem
from app.services.question_certification_service import (
    LEGACY_QUESTION_CERTIFICATION_RULE_VERSION,
    QUESTION_CERTIFICATION_RULE_VERSION,
    certify_question_payloads,
    knowledge_item_content_hash,
)
from app.services.question_source_binding_service import candidate_chunks_for_item


def _payload(
    question: DiagnosticQuestion,
    item_by_public_id: dict[str, KnowledgeItem],
) -> dict | None:
    answer_key = dict(question.answer_key_json or {})
    source_ref_ids = [str(value) for value in answer_key.get("source_ref_ids") or []]
    chunks = {
        chunk.chunk_id: (item, chunk)
        for item in item_by_public_id.values()
        for chunk in candidate_chunks_for_item(item)
    }
    if not source_ref_ids or any(source_ref_id not in chunks for source_ref_id in source_ref_ids):
        return None
    source_chunks = []
    for source_ref_id in source_ref_ids:
        source_item, chunk = chunks[source_ref_id]
        source_chunks.append(
            {
                "chunk_id": chunk.chunk_id,
                "chunk_index": chunk.chunk_index,
                "knowledge_candidate_id": source_item.public_id,
                "knowledge_id": source_item.public_id,
                "source_locator": (answer_key.get("source_locators") or {}).get(source_ref_id),
                "content": chunk.content,
                "source_content_hash": knowledge_item_content_hash(source_item),
                "chunker_version": answer_key.get("chunker_version"),
            }
        )
    return {
        "knowledge_candidate_id": item_by_public_id[
            source_ref_ids[0].split("::chunk::", 1)[0]
        ].public_id,
        "related_knowledge_candidate_ids": [
            value.split("::chunk::", 1)[0] for value in source_ref_ids[1:]
        ],
        "question_type": question.question_type,
        "stem": question.stem,
        "options": list(question.options_json or []),
        "answer": (
            answer_key.get("correct_option")
            if question.question_type == "single_choice"
            else answer_key.get("answer")
        ),
        "explanation": answer_key.get("explanation"),
        "rubric": list(answer_key.get("rubric") or []),
        "difficulty": question.difficulty,
        "quiz_level": answer_key.get("quiz_level"),
        "question_bank_uses": list(answer_key.get("question_bank_uses") or []),
        "source_chunks": source_chunks,
        "source_content_hash": question.source_content_hash,
        "evidence_quotes": list(answer_key.get("evidence_quotes") or []),
    }


def recertify(domain_code: str, *, dry_run: bool) -> dict[str, int]:
    counts = {"examined": 0, "certified": 0, "stale": 0}
    with SessionLocal() as db:
        items = list(
            db.scalars(
                select(KnowledgeItem).where(KnowledgeItem.domain_code == domain_code)
            )
        )
        item_by_public_id = {item.public_id: item for item in items}
        questions = list(
            db.scalars(
                select(DiagnosticQuestion).where(
                    DiagnosticQuestion.domain_code == domain_code,
                    DiagnosticQuestion.status == "active",
                    DiagnosticQuestion.certification_status == "certified",
                    DiagnosticQuestion.certification_rule_version
                    == LEGACY_QUESTION_CERTIFICATION_RULE_VERSION,
                )
            )
        )
        counts["examined"] = len(questions)
        payloads: list[tuple[str, dict]] = []
        question_by_id = {question.public_id: question for question in questions}
        for question in questions:
            payload = _payload(question, item_by_public_id)
            if payload is None:
                counts["stale"] += 1
                if not dry_run:
                    question.certification_status = "stale"
                    question.certified_at = None
                continue
            payloads.append((question.public_id, payload))
        for question_id, result in certify_question_payloads(payloads).items():
            question = question_by_id[question_id]
            if result.issue_kind == "valid":
                counts["certified"] += 1
                if not dry_run:
                    question.certification_rule_version = QUESTION_CERTIFICATION_RULE_VERSION
                    question.certification_report_json = result.report
                    question.certified_at = datetime.now(UTC).replace(tzinfo=None)
            else:
                counts["stale"] += 1
                if not dry_run:
                    question.certification_status = "stale"
                    question.certification_report_json = result.report
                    question.certified_at = None
        if dry_run:
            db.rollback()
        else:
            db.commit()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-certify formal questions with question-cert-v2")
    parser.add_argument("--domain-code", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(recertify(args.domain_code, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
