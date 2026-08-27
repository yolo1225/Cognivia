from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.domain_evidence_policy import classify_evidence_capabilities
from app.models import (
    KnowledgeDocument,
    KnowledgeImportCandidate,
    KnowledgeImportRun,
    KnowledgeItem,
)
from app.services.knowledge_parser_service import parse_document
from app.services.ability_weight_service import ability_weight_gate
from app.services.question_certification_service import (
    QUESTION_CERTIFICATION_RULE_VERSION,
    deterministic_certification_issues,
)


ALLOWED_EVIDENCE = {
    "concept",
    "operation",
    "command",
    "code_example",
    "expected_result",
    "error_handling",
    "version_boundary",
}


def _is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


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
    enforce_question_bank = db.scalar(
        select(KnowledgeImportRun.id).where(KnowledgeImportRun.document_id == document_id)
    ) is not None
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
        elif item.candidate_type == "diagnostic_question":
            if payload.get("knowledge_candidate_id") not in by_id:
                errors.append("关联知识候选不存在")
            if (
                _is_blank(payload.get("stem"))
                or _is_blank(payload.get("answer"))
                or _is_blank(payload.get("explanation"))
            ):
                errors.append("题干、答案和解析不能为空")
            if payload.get("question_type") in {"choice", "single_choice"}:
                options = payload.get("options") or []
                answer = payload.get("answer")
                answer_is_index = isinstance(answer, int) and 0 <= answer < len(options)
                if not answer_is_index and answer not in options:
                    errors.append("选择题答案不在选项中")
                if len(options) != len({str(option).strip() for option in options}):
                    errors.append("选择题选项重复")
            if "来源章节的知识主题" in str(payload.get("stem") or ""):
                errors.append("诊断题不能只考查章节标题识别")
            if _is_blank(payload.get("source_quote")):
                errors.append("诊断题缺少来源依据")
            if enforce_question_bank:
                if (
                    payload.get("certification_status") != "certified"
                    or payload.get("certification_rule_version")
                    != QUESTION_CERTIFICATION_RULE_VERSION
                ):
                    errors.append("正式题目尚未通过认证")
                deterministic_issues = deterministic_certification_issues(
                    {"candidate_id": item.public_id, **payload}
                )
                if deterministic_issues:
                    errors.append(
                        "正式题目证据或结构失效："
                        + ",".join(deterministic_issues[0].fields)
                    )
                if payload.get("question_type") not in {"single_choice", "short_answer"}:
                    errors.append("正式题库题型不合法")
                if payload.get("quiz_level") not in {
                    "foundation", "improvement", "challenge"
                }:
                    errors.append("正式题库教学层级不合法")
        elif item.candidate_type == "knowledge_relation":
            source, target = payload.get("source_candidate_id"), payload.get("target_candidate_id")
            relation_type = str(payload.get("relation_type") or "")
            if source == target:
                errors.append("知识关系不能自环")
            if source not in by_id or target not in by_id:
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
    if enforce_question_bank:
        questions_by_knowledge: dict[str, list[KnowledgeImportCandidate]] = defaultdict(list)
        for item in candidates:
            if item.candidate_type == "diagnostic_question":
                knowledge_id = str(
                    (item.payload_json or {}).get("knowledge_candidate_id") or ""
                )
                questions_by_knowledge[knowledge_id].append(item)
        for item in candidates:
            if item.candidate_type != "knowledge_item":
                continue
            questions = [
                question
                for question in questions_by_knowledge.get(item.public_id, [])
                if not question.validation_errors_json
            ]
            if not questions:
                item.validation_errors_json = list(item.validation_errors_json or []) + [
                    "正式题库必须至少包含1道以该知识点为主要归因的题目"
                ]
                item.status = "needs_edit"
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
