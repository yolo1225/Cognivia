from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.domain_evidence_policy import classify_evidence_capabilities
from app.models import (
    KnowledgeDocument,
    KnowledgeImportCandidate,
    KnowledgeItem,
)
from app.services.knowledge_parser_service import parse_document
from app.services.ability_weight_service import ability_weight_gate


ALLOWED_EVIDENCE = {
    "concept",
    "operation",
    "command",
    "code_example",
    "expected_result",
    "error_handling",
    "version_boundary",
}
def validate_import(db: Session, document_id: int) -> dict[str, int]:
    document = db.get(KnowledgeDocument, document_id)
    if document is None:
        raise ValueError("知识导入文档不存在")
    source_texts = [section["text"] for section in parse_document(document)]
    candidates = list(
        db.scalars(
            select(KnowledgeImportCandidate).where(
                KnowledgeImportCandidate.document_id == document_id
            )
        )
    )
    by_id = {item.public_id: item for item in candidates}
    names: set[str] = set()
    graph: dict[str, list[str]] = defaultdict(list)
    relation_keys: set[tuple[str, str, str]] = set()
    invalid = 0
    for item in candidates:
        payload = item.payload_json or {}
        errors: list[str] = []
        if not item.source_locator_json or not item.source_locator_json.get("checksum"):
            errors.append("缺少可追溯来源")
        if item.candidate_type == "knowledge_item":
            name = str(payload.get("name", "")).strip()
            if not name or not str(payload.get("content", "")).strip():
                errors.append("知识名称和正文不能为空")
            source_quote = str(payload.get("source_quote", "")).strip()
            if not source_quote or not any(source_quote in text for text in source_texts):
                errors.append("来源摘录无法在原文中定位")
            if not 1 <= int(payload.get("difficulty", 0) or 0) <= 5:
                errors.append("难度必须为 1 到 5")
            errors.extend(ability_weight_gate(payload))
            derived_capabilities = classify_evidence_capabilities(str(payload.get("content") or ""))
            if payload.get("evidence_capabilities") != derived_capabilities:
                payload["evidence_capabilities"] = derived_capabilities
                item.payload_json = dict(payload)
            if set(derived_capabilities) - ALLOWED_EVIDENCE:
                errors.append("证据能力不合法")
            normalized = name.casefold()
            if normalized in names or (
                payload.get("action") == "create" and db.scalar(
                    select(KnowledgeItem.id).where(
                        KnowledgeItem.domain_code == item.domain_code, KnowledgeItem.name == name
                    )
                )
                is not None
            ):
                errors.append("知识点重复")
            names.add(normalized)
        elif item.candidate_type == "knowledge_relation":
            source = payload.get("source_candidate_id") or payload.get("source_existing_knowledge_id")
            target = payload.get("target_candidate_id") or payload.get("target_existing_knowledge_id")
            relation_type = str(payload.get("relation_type") or "")
            if source == target:
                errors.append("知识关系不能自环")
            source_exists = source in by_id or db.scalar(
                select(KnowledgeItem.id).where(
                    KnowledgeItem.domain_code == document.domain_code,
                    KnowledgeItem.public_id == source,
                    KnowledgeItem.status == "published",
                )
            ) is not None
            target_exists = target in by_id or db.scalar(
                select(KnowledgeItem.id).where(
                    KnowledgeItem.domain_code == document.domain_code,
                    KnowledgeItem.public_id == target,
                    KnowledgeItem.status == "published",
                )
            ) is not None
            if not source_exists or not target_exists:
                errors.append("知识关系端点不存在")
            if relation_type not in {"prerequisite", "depends_on", "next_step", "related_to"}:
                errors.append("知识关系类型不合法")
            key = (str(source), str(target), relation_type)
            if key in relation_keys:
                errors.append("知识关系重复")
            relation_keys.add(key)
            if not (
                payload.get("source_quote")
                or payload.get("evidence_chunk_ids")
                or (item.source_locator_json or {}).get("chunk_id")
            ):
                errors.append("知识关系缺少证据")
            if relation_type in {"prerequisite", "next_step"}:
                graph[source].append(target)
            elif relation_type == "depends_on":
                graph[target].append(source)
        else:
            errors.append("未知候选类型")
        item.validation_errors_json = errors
        if errors:
            item.status = "needs_edit"
            invalid += 1
    visiting: set[str] = set()
    visited: set[str] = set()

    def cyclic(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        found = any(cyclic(child) for child in graph[node])
        visiting.remove(node)
        visited.add(node)
        return found

    if any(cyclic(node) for node in list(graph)):
        for item in candidates:
            if (
                item.candidate_type == "knowledge_relation"
                and (item.payload_json or {}).get("relation_type") == "prerequisite"
            ):
                item.validation_errors_json = list(item.validation_errors_json or []) + [
                    "前置关系存在环"
                ]
                item.status = "needs_edit"
        invalid = sum(bool(item.validation_errors_json) for item in candidates)
    invalid = sum(bool(item.validation_errors_json) for item in candidates)
    db.commit()
    return {"total": len(candidates), "valid": len(candidates) - invalid, "invalid": invalid}
