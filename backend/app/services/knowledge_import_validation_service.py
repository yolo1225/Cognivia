from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import KnowledgeDocument, KnowledgeImportCandidate, KnowledgeItem
from app.services.knowledge_parser_service import parse_document


ALLOWED_EVIDENCE = {
    "concept",
    "definition",
    "example",
    "operation",
    "command",
    "code",
    "code_example",
    "expected_result",
    "troubleshooting",
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
            weights = payload.get("ability_weights") or {}
            if (
                abs(
                    sum(
                        float(weights.get(key, 0))
                        for key in (
                            "theory",
                            "practice",
                            "problem_solving",
                            "knowledge_breadth",
                        )
                    )
                    - 1
                )
                > 0.001
                or float(weights.get("learning_speed", 0)) != 0
            ):
                errors.append("能力权重不合法")
            if set(payload.get("evidence_capabilities") or []) - ALLOWED_EVIDENCE:
                errors.append("证据能力不合法")
            normalized = name.casefold()
            if (
                normalized in names
                or db.scalar(
                    select(KnowledgeItem.id).where(
                        KnowledgeItem.domain_code == item.domain_code, KnowledgeItem.name == name
                    )
                )
                is not None
            ):
                errors.append("知识点重复")
            names.add(normalized)
        elif item.candidate_type == "diagnostic_question":
            if payload.get("knowledge_candidate_id") not in by_id:
                errors.append("关联知识候选不存在")
            if (
                not payload.get("stem")
                or not payload.get("answer")
                or not payload.get("explanation")
            ):
                errors.append("题干、答案和解析不能为空")
            if payload.get("question_type") in {"choice", "single_choice"}:
                options = payload.get("options") or []
                answer = payload.get("answer")
                answer_is_index = isinstance(answer, int) and 0 <= answer < len(options)
                if not answer_is_index and answer not in options:
                    errors.append("选择题答案不在选项中")
        elif item.candidate_type == "knowledge_relation":
            source, target = payload.get("source_candidate_id"), payload.get("target_candidate_id")
            if source == target:
                errors.append("知识关系不能自环")
            if source not in by_id or target not in by_id:
                errors.append("知识关系端点不存在")
            if payload.get("relation_type") == "prerequisite":
                graph[source].append(target)
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
    db.commit()
    return {"total": len(candidates), "valid": len(candidates) - invalid, "invalid": invalid}
