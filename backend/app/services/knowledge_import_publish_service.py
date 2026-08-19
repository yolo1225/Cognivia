from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    DiagnosticQuestion,
    KnowledgeDocument,
    KnowledgeImportCandidate,
    KnowledgeItem,
    KnowledgeRelation,
)


class KnowledgeImportPublishError(ValueError):
    pass


def approve_candidates(
    db: Session, document: KnowledgeDocument, candidate_ids: list[str] | None = None
) -> int:
    candidates = list(
        db.scalars(
            select(KnowledgeImportCandidate).where(
                KnowledgeImportCandidate.document_id == document.id
            )
        )
    )
    selected = set(candidate_ids or [item.public_id for item in candidates])
    by_id = {item.public_id: item for item in candidates}
    missing_dependencies: set[str] = set()
    for item in candidates:
        if item.public_id not in selected:
            continue
        payload = item.payload_json or {}
        references = []
        if item.candidate_type == "knowledge_relation":
            references = [
                payload.get("source_candidate_id"),
                payload.get("target_candidate_id"),
            ]
        elif item.candidate_type == "diagnostic_question":
            references = [payload.get("knowledge_candidate_id")]
        missing_dependencies.update(
            reference
            for reference in references
            if reference in by_id and reference not in selected
        )
    if missing_dependencies:
        raise KnowledgeImportPublishError(
            "候选批准缺少引用依赖：" + ", ".join(sorted(missing_dependencies)[:5])
        )
    blocked = [
        item.public_id
        for item in candidates
        if item.public_id in selected and item.validation_errors_json
    ]
    if blocked:
        raise KnowledgeImportPublishError(f"存在未通过校验的候选：{', '.join(blocked[:5])}")
    count = 0
    for item in candidates:
        if item.public_id in selected:
            item.status = "approved"
            count += 1
    db.flush()
    return count


def publish_approved(db: Session, document: KnowledgeDocument) -> dict[str, int]:
    candidates = list(
        db.scalars(
            select(KnowledgeImportCandidate).where(
                KnowledgeImportCandidate.document_id == document.id,
                KnowledgeImportCandidate.status == "approved",
            )
        )
    )
    if not candidates:
        raise KnowledgeImportPublishError("没有已批准候选")
    knowledge_map: dict[str, KnowledgeItem] = {}
    for candidate in candidates:
        if candidate.candidate_type != "knowledge_item":
            continue
        payload = candidate.payload_json
        item = KnowledgeItem(
            public_id=f"ki_{uuid4().hex[:12]}",
            domain_code=document.domain_code,
            name=str(payload["name"])[:255],
            category=str(payload.get("category") or "未分类")[:64],
            difficulty=int(payload["difficulty"]),
            tags_json=payload.get("tags") or [],
            evidence_capabilities_json=payload.get("evidence_capabilities") or [],
            content_md=payload["content"],
            source_title=document.source_title,
            source_url=None,
            license_note=document.license_note,
            needs_reembedding=True,
            source_document_id=document.id,
            ability_weights_json=payload.get("ability_weights") or {},
            source_locator_json=candidate.source_locator_json or {},
            status="published",
        )
        db.add(item)
        db.flush()
        knowledge_map[candidate.public_id] = item
    relation_count = 0
    question_count = 0
    for candidate in candidates:
        payload = candidate.payload_json
        if candidate.candidate_type == "knowledge_relation":
            source = knowledge_map.get(payload.get("source_candidate_id"))
            target = knowledge_map.get(payload.get("target_candidate_id"))
            if source and target:
                db.add(
                    KnowledgeRelation(
                        source_item_id=source.id,
                        target_item_id=target.id,
                        relation_type=payload.get("relation_type", "related"),
                    )
                )
                relation_count += 1
        elif candidate.candidate_type == "diagnostic_question":
            item = knowledge_map.get(payload.get("knowledge_candidate_id"))
            if item:
                db.add(
                    DiagnosticQuestion(
                        public_id=f"dq_{uuid4().hex[:12]}",
                        domain_code=document.domain_code,
                        knowledge_item_id=item.id,
                        question_type=payload.get("question_type", "short_answer"),
                        stem=payload["stem"],
                        options_json=payload.get("options") or [],
                        answer_key_json={
                            "answer": payload["answer"],
                            "rubric": payload.get("rubric") or [],
                            "explanation": payload.get("explanation", ""),
                        },
                        difficulty=int(payload.get("difficulty", 2)),
                    )
                )
                question_count += 1
    for candidate in candidates:
        candidate.status = "published"
    document.status = "index_pending"
    document.knowledge_item_count = len(knowledge_map)
    db.commit()
    return {
        "knowledge_items": len(knowledge_map),
        "relations": relation_count,
        "questions": question_count,
    }
