from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import KnowledgeDocument, KnowledgeImportCandidate


DEFAULT_WEIGHTS = {
    "theory": 0.35,
    "practice": 0.35,
    "problem_solving": 0.2,
    "breadth": 0.1,
    "learning_speed": 0.0,
}


def _candidate_id(document_id: str, candidate_type: str, stable_key: str) -> str:
    digest = hashlib.sha256(f"{document_id}:{candidate_type}:{stable_key}".encode()).hexdigest()[
        :16
    ]
    return f"kic_{digest}"


def replace_candidates(
    db: Session, document: KnowledgeDocument, sections: list[dict[str, Any]]
) -> list[KnowledgeImportCandidate]:
    db.execute(
        delete(KnowledgeImportCandidate).where(KnowledgeImportCandidate.document_id == document.id)
    )
    candidates: list[KnowledgeImportCandidate] = []
    knowledge_ids: list[str] = []
    for index, section in enumerate(sections, start=1):
        heading = " / ".join(section["heading_path"])
        public_id = _candidate_id(document.public_id, "knowledge_item", section["checksum"])
        knowledge_ids.append(public_id)
        locator = {
            key: section.get(key) for key in ("heading_path", "page_start", "page_end", "checksum")
        }
        knowledge = KnowledgeImportCandidate(
            public_id=public_id,
            document_id=document.id,
            domain_code=document.domain_code,
            candidate_type="knowledge_item",
            payload_json={
                "name": heading[:255],
                "category": section["heading_path"][0][:64],
                "content": section["text"],
                "difficulty": 2,
                "tags": ["document-import"],
                "ability_weights": DEFAULT_WEIGHTS,
                "evidence_capabilities": ["definition"],
                "source_quote": section["text"][:300],
            },
            source_locator_json=locator,
            confidence=0.85,
            status="pending",
            validation_errors_json=[],
        )
        question = KnowledgeImportCandidate(
            public_id=_candidate_id(document.public_id, "diagnostic_question", section["checksum"]),
            document_id=document.id,
            domain_code=document.domain_code,
            candidate_type="diagnostic_question",
            payload_json={
                "knowledge_candidate_id": public_id,
                "question_type": "short_answer",
                "stem": f"请概括“{heading}”的核心要点。",
                "options": [],
                "answer": section["text"][:300],
                "rubric": ["答案应覆盖来源章节的关键概念"],
                "explanation": f"依据来源章节：{heading}",
                "difficulty": 2,
            },
            source_locator_json=locator,
            confidence=0.75,
            status="pending",
            validation_errors_json=[],
        )
        candidates.extend([knowledge, question])
        if index > 1:
            candidates.append(
                KnowledgeImportCandidate(
                    public_id=_candidate_id(
                        document.public_id, "knowledge_relation", f"{knowledge_ids[-2]}:{public_id}"
                    ),
                    document_id=document.id,
                    domain_code=document.domain_code,
                    candidate_type="knowledge_relation",
                    payload_json={
                        "source_candidate_id": knowledge_ids[-2],
                        "target_candidate_id": public_id,
                        "relation_type": "prerequisite",
                        "reason": "文档章节顺序",
                    },
                    source_locator_json=locator,
                    confidence=0.6,
                    status="pending",
                    validation_errors_json=[],
                )
            )
    db.add_all(candidates)
    return candidates
