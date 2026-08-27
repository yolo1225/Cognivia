from __future__ import annotations

import hashlib
import re
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.agents.domain_evidence_policy import classify_evidence_capabilities
from app.models import KnowledgeDocument, KnowledgeImportCandidate, KnowledgeItem


SOURCE_KNOWLEDGE_PREFIX = re.compile(
    r"^.*?\([a-z][a-z0-9_-]*\)\s*[/／]\s*\d+\s*[.．、:-]?\s*",
    re.IGNORECASE,
)


def normalize_knowledge_name(value: str) -> str:
    normalized = SOURCE_KNOWLEDGE_PREFIX.sub("", value.strip()).strip()
    return normalized or value.strip()


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
    external_to_candidate: dict[str, str] = {}
    for index, section in enumerate(sections, start=1):
        heading = normalize_knowledge_name(" / ".join(section["heading_path"]))
        metadata = dict(section.get("metadata") or {})
        external_id = str(metadata.get("knowledge_id") or "").strip() or None
        public_id = _candidate_id(document.public_id, "knowledge_item", section["checksum"])
        knowledge_ids.append(public_id)
        if external_id:
            external_to_candidate[external_id] = public_id
        existing = None
        if external_id:
            existing = db.scalar(
                select(KnowledgeItem).where(
                    KnowledgeItem.domain_code == document.domain_code,
                    KnowledgeItem.external_id == external_id,
                )
            )
        if existing is None:
            existing = db.scalar(
                select(KnowledgeItem).where(
                    KnowledgeItem.domain_code == document.domain_code,
                    KnowledgeItem.name == heading,
                    KnowledgeItem.status == "published",
                )
            )
        target_public_id = existing.public_id if existing else (
            "ki_" + hashlib.sha256(
                f"{document.domain_code}:{external_id or section['checksum']}".encode()
            ).hexdigest()[:16]
        )
        before_checksum = (
            hashlib.sha256(existing.content_md.encode()).hexdigest() if existing else None
        )
        action = "create" if existing is None else (
            "skip" if before_checksum == section["checksum"] else "update"
        )
        evidence_capabilities = classify_evidence_capabilities(section["text"])
        explicit_weights = metadata.get("ability_weights")
        locator = {
            key: section.get(key) for key in ("heading_path", "page_start", "page_end", "checksum")
        }
        locator["chunk_id"] = section.get("chunk_public_id")
        knowledge = KnowledgeImportCandidate(
            public_id=public_id,
            document_id=document.id,
            domain_code=document.domain_code,
            candidate_type="knowledge_item",
            payload_json={
                "name": heading[:255],
                "external_id": external_id,
                "action": action,
                "target_public_id": target_public_id,
                "before_checksum": before_checksum,
                "after_checksum": section["checksum"],
                "source_chunk_ids": [section.get("chunk_public_id")],
                "category": str(metadata.get("category") or section["heading_path"][0])[:64],
                "content": section["text"],
                "difficulty": int(metadata.get("difficulty") or 2),
                "tags": metadata.get("tags") or ["document-import"],
                "ability_weights": explicit_weights,
                "ability_weight_source": "explicit" if explicit_weights else "missing",
                "ability_weight_confidence": 1.0 if explicit_weights else 0.0,
                "evidence_capabilities": evidence_capabilities,
                "source_quote": section["text"][:300],
                "source_title": metadata.get("source_title") or document.source_title,
                "source_url": metadata.get("source_url"),
                "license_note": metadata.get("license") or document.license_note,
                "prerequisites": metadata.get("prerequisites") or [],
            },
            source_locator_json=locator,
            confidence=0.85,
            status="pending",
            validation_errors_json=[],
        )
        source_statement = next(
            (line.strip() for line in section["text"].splitlines() if len(line.strip()) >= 12),
            section["text"][:180],
        )[:220]
        distractors = []
        for other in sections:
            if other["checksum"] == section["checksum"]:
                continue
            statement = next(
                (line.strip() for line in other["text"].splitlines() if len(line.strip()) >= 12),
                other["text"][:180],
            )[:220]
            if statement and statement != source_statement and statement not in distractors:
                distractors.append(statement)
            if len(distractors) == 3:
                break
        single_choice = len(distractors) == 3 and (index - 1) % 5 < 3
        practical = "operation" in (knowledge.payload_json or {}).get("evidence_capabilities", [])
        question_dimension = (
            "错误诊断与修复" if practical and index % 2 == 0
            else "实操场景选择" if practical
            else "机制与因果" if index % 2 == 0
            else "概念理解"
        )
        options = [source_statement, *distractors] if single_choice else []
        if single_choice:
            answer_index = (index - 1) % len(options)
            options[0], options[answer_index] = options[answer_index], options[0]
        else:
            answer_index = None
        question = KnowledgeImportCandidate(
            public_id=_candidate_id(document.public_id, "diagnostic_question", section["checksum"]),
            document_id=document.id,
            domain_code=document.domain_code,
            candidate_type="diagnostic_question",
            payload_json={
                "knowledge_candidate_id": public_id,
                "question_type": "single_choice" if single_choice else "short_answer",
                "stem": (
                    f"关于“{heading}”，下列哪项表述与来源材料一致？"
                    if single_choice
                    else (
                        f"结合来源材料，说明“{heading}”的关键机制、适用条件和一个判断依据。"
                        if not practical
                        else f"在“{heading}”相关实践中，说明关键操作、预期结果和出现异常时的排查依据。"
                    )
                ),
                "options": options,
                "answer": (answer_index if single_choice else source_statement),
                "rubric": [
                    "包含来源支持的核心概念或操作",
                    "说明适用条件或判断依据",
                    "不引入来源无法支持的结论",
                ],
                "explanation": f"正确结论可由来源摘录直接验证：{source_statement}",
                "difficulty": 2,
                "diagnostic_dimension": question_dimension,
                "source_quote": source_statement,
            },
            source_locator_json=locator,
            confidence=0.75,
            status="pending",
            validation_errors_json=[],
        )
        candidates.extend([knowledge, question])
    for section, target_candidate in zip(sections, knowledge_ids, strict=True):
        for prerequisite in (section.get("metadata") or {}).get("prerequisites", []):
            source_candidate = external_to_candidate.get(str(prerequisite))
            if not source_candidate:
                continue
            candidates.append(
                KnowledgeImportCandidate(
                    public_id=_candidate_id(
                        document.public_id, "knowledge_relation", f"{source_candidate}:{target_candidate}"
                    ),
                    document_id=document.id,
                    domain_code=document.domain_code,
                    candidate_type="knowledge_relation",
                    payload_json={
                        "source_candidate_id": source_candidate,
                        "target_candidate_id": target_candidate,
                        "relation_type": "prerequisite",
                        "reason": "结构化 prerequisites 字段",
                        "generation_method": "explicit",
                        "evidence_chunk_ids": [section.get("chunk_public_id")],
                    },
                    source_locator_json={"chunk_id": section.get("chunk_public_id"), "checksum": section["checksum"]},
                    confidence=1.0,
                    status="pending",
                    validation_errors_json=[],
                )
            )
    db.add_all(candidates)
    return candidates
