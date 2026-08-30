from __future__ import annotations

import hashlib
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    DiagnosticQuestion,
    KnowledgeItem,
)
from app.rag.candidate_chunker import CHUNKER_VERSION
from app.services.llm_service import ModelGatewayError, ModelResponseError, gateway


QUESTION_CERTIFICATION_RULE_VERSION = "question-cert-v2"
LEGACY_QUESTION_CERTIFICATION_RULE_VERSION = "question-cert-v1"
ACCEPTED_QUESTION_CERTIFICATION_RULE_VERSIONS = {
    LEGACY_QUESTION_CERTIFICATION_RULE_VERSION,
    QUESTION_CERTIFICATION_RULE_VERSION,
}
_SPACE_RE = re.compile(r"\s+")
logger = logging.getLogger(__name__)
CERTIFICATION_FIELDS = Literal[
    "stem", "options", "answer", "explanation", "rubric", "difficulty", "source"
]
_CERTIFICATION_FIELD_ALIASES = {
    "question": "stem",
    "question_text": "stem",
    "question_stem": "stem",
    "option": "options",
    "distractors": "options",
    "correct_answer": "answer",
    "answer_key": "answer",
    "analysis": "explanation",
    "rationale": "explanation",
    "rubrics": "rubric",
    "scoring_points": "rubric",
    "level": "difficulty",
    "evidence": "source",
    "source_chunks": "source",
    "source_ref_ids": "source",
}


class CertificationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    fields: list[str] = []
    reason: str = ""


class CertificationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    verdict: Literal["pass", "fail"]
    failed_fields: list[CERTIFICATION_FIELDS] = Field(default_factory=list)
    reason: str = ""
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_optional_empty_lists(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        # Qwen commonly emits null for semantically empty arrays. This is the
        # only provider-shape normalization allowed; names, verdicts, fields
        # and failed-decision reasons remain strict.
        for field in ("failed_fields", "warnings"):
            if normalized.get(field) in (None, ""):
                normalized[field] = []
            elif isinstance(normalized.get(field), str):
                normalized[field] = (
                    [
                        value.strip()
                        for value in re.split(r"[,，]", normalized[field])
                        if value.strip()
                    ]
                    if field == "failed_fields"
                    else [normalized[field]]
                )
        failed_fields = normalized.get("failed_fields")
        if isinstance(failed_fields, list):
            normalized["failed_fields"] = [
                _CERTIFICATION_FIELD_ALIASES.get(str(field), field)
                for field in failed_fields
            ]
        return normalized

    @model_validator(mode="after")
    def require_actionable_failure(self) -> "CertificationDecision":
        self.question_id = self.question_id.strip()
        self.reason = self.reason.strip()
        self.warnings = [value.strip() for value in self.warnings if value.strip()]
        if not self.question_id:
            raise ValueError("question_id is required")
        if self.verdict == "fail" and (not self.failed_fields or not self.reason):
            raise ValueError("failed decisions require failed_fields and reason")
        if self.verdict == "pass" and self.failed_fields:
            raise ValueError("passed decisions cannot contain failed_fields")
        return self


class CertificationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[CertificationDecision]


class QuestionCertificationResult(BaseModel):
    question_id: str
    issue_kind: Literal["valid", "content_rejected", "certification_service_error"]
    issue_fields: list[str] = Field(default_factory=list)
    issue_reason: str = ""
    warnings: list[str] = Field(default_factory=list)
    report: dict[str, Any] = Field(default_factory=dict)


def normalize_evidence_text(value: object) -> str:
    """Normalize formatting only; word order and characters remain unchanged."""

    return _SPACE_RE.sub("", str(value or "")).strip()


def canonical_knowledge_content_hash(
    *,
    knowledge_id: str,
    domain_code: str,
    name: str,
    category: str,
    difficulty: int,
    tags: list[str],
    evidence_capabilities: list[str],
    content: str,
    source_title: str,
    source_url: str | None,
    license_note: str,
) -> str:
    payload = {
        "knowledge_id": knowledge_id,
        "domain_code": domain_code,
        "name": name,
        "category": category,
        "difficulty": difficulty,
        "tags": list(tags),
        "evidence_capabilities": list(evidence_capabilities),
        "content": content,
        "source_title": source_title,
        "source_url": source_url,
        "license_note": license_note,
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def knowledge_item_content_hash(item: KnowledgeItem) -> str:
    return canonical_knowledge_content_hash(
        knowledge_id=item.public_id,
        domain_code=item.domain_code,
        name=item.name,
        category=item.category,
        difficulty=item.difficulty,
        tags=list(item.tags_json or []),
        evidence_capabilities=list(item.evidence_capabilities_json or []),
        content=item.content_md,
        source_title=item.source_title,
        source_url=item.source_url,
        license_note=item.license_note,
    )


def mark_question_certifications_stale(
    db: Session,
    *,
    domain_code: str,
    knowledge_ids: set[str],
) -> int:
    if not knowledge_ids:
        return 0
    questions = list(
        db.scalars(
            select(DiagnosticQuestion).where(
                DiagnosticQuestion.domain_code == domain_code,
                DiagnosticQuestion.status == "active",
                DiagnosticQuestion.certification_status == "certified",
            )
        )
    )
    changed = 0
    for question in questions:
        answer = dict(question.answer_key_json or {})
        source_knowledge_ids = {
            str(value).split("::chunk::", 1)[0]
            for value in answer.get("source_ref_ids") or []
        }
        if source_knowledge_ids.intersection(knowledge_ids):
            question.certification_status = "stale"
            question.certified_at = None
            report = dict(question.certification_report_json or {})
            report["stale_reason"] = "source_or_chunker_changed"
            question.certification_report_json = report
            changed += 1
    db.flush()
    return changed


def deterministic_certification_issues(
    payload: dict[str, Any],
) -> list[CertificationIssue]:
    question_id = str(payload.get("candidate_id") or payload.get("question_id") or "")
    failed: list[str] = []
    source_chunks = [
        dict(value) for value in payload.get("source_chunks") or [] if isinstance(value, dict)
    ]
    chunks_by_ref = {
        str(value.get("chunk_id") or ""): value for value in source_chunks
    }
    primary_candidate_id = str(
        payload.get("knowledge_candidate_id") or payload.get("knowledge_id") or ""
    )
    related_candidate_ids = [
        str(value) for value in payload.get("related_knowledge_candidate_ids") or []
    ]
    quotes = [
        dict(value) for value in payload.get("evidence_quotes") or [] if isinstance(value, dict)
    ]
    if not question_id:
        failed.append("question_id")
    if not primary_candidate_id:
        failed.append("knowledge_id")
    quiz_level = str(payload.get("quiz_level") or "")
    max_chunks = {"foundation": 1, "improvement": 2, "challenge": 3}.get(quiz_level, 0)
    if not source_chunks or len(source_chunks) > max_chunks:
        failed.append("source_chunks")
    source_candidate_ids = [
        str(value.get("knowledge_candidate_id") or "") for value in source_chunks
    ]
    if source_chunks and (
        source_candidate_ids[0] != primary_candidate_id
        or source_candidate_ids[1:] != related_candidate_ids
        or len(source_candidate_ids) != len(set(source_candidate_ids))
    ):
        failed.append("related_knowledge_ids")
    if len(chunks_by_ref) != len(source_chunks) or "" in chunks_by_ref:
        failed.append("source_ref_ids")
    if any(
        not str(value.get("chunk_id") or "").endswith(
            f"::chunk::{int(value.get('chunk_index') or 0)}"
        )
        for value in source_chunks
    ):
        failed.append("source_ref_ids")
    if any(not str(value.get("source_locator") or "") for value in source_chunks):
        failed.append("source_locators")
    if any(value.get("chunker_version") != CHUNKER_VERSION for value in source_chunks):
        failed.append("chunker_version")
    if any(
        not str(value.get("source_content_hash") or "").startswith("sha256:")
        or len(str(value.get("source_content_hash") or "")) != 71
        for value in source_chunks
    ):
        failed.append("source_content_hashes")
    source_hash = str(payload.get("source_content_hash") or "")
    expected_source_hash = "sha256:" + hashlib.sha256(
        json.dumps(
            {
                str(value.get("chunk_id") or ""): str(
                    value.get("source_content_hash") or ""
                )
                for value in source_chunks
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    if source_hash != expected_source_hash:
        failed.append("source_content_hash")
    if not 1 <= len(quotes) <= 3:
        failed.append("evidence_quotes")
    else:
        for evidence in quotes:
            source_ref_id = str(evidence.get("source_ref_id") or "")
            quote = normalize_evidence_text(evidence.get("quote"))
            source = chunks_by_ref.get(source_ref_id)
            if (
                source is None
                or not quote
                or quote not in normalize_evidence_text(source.get("content"))
            ):
                failed.append("evidence_quotes")
                break

    question_type = str(payload.get("question_type") or "")
    options = [str(value).strip() for value in payload.get("options") or []]
    answer = payload.get("answer")
    rubric = [str(value).strip() for value in payload.get("rubric") or [] if str(value).strip()]
    if not str(payload.get("stem") or "").strip():
        failed.append("stem")
    if not str(payload.get("explanation") or "").strip():
        failed.append("explanation")
    if not 1 <= int(payload.get("difficulty") or 0) <= 5:
        failed.append("difficulty")
    if quiz_level not in {"foundation", "improvement", "challenge"}:
        failed.append("quiz_level")
    purposes = payload.get("question_bank_uses")
    if (
        not isinstance(purposes, list)
        or len(purposes) != 1
        or str(purposes[0])
        not in {"diagnosis", "graded_quiz", "mastery_validation"}
    ):
        failed.append("question_bank_uses")
    if question_type == "single_choice":
        if (
            len(options) != 4
            or len(set(options)) != 4
            or not isinstance(answer, int)
            or not 0 <= answer < 4
        ):
            failed.extend(["options", "answer"])
    elif question_type == "short_answer":
        if not isinstance(answer, str) or not answer.strip():
            failed.append("answer")
        if not 2 <= len(rubric) <= 8:
            failed.append("rubric")
    else:
        failed.append("question_type")
    if not failed:
        return []
    return [
        CertificationIssue(
            question_id=question_id,
            fields=list(dict.fromkeys(failed)),
            reason="deterministic_validation_failed",
        )
    ]


QUESTION_CERTIFICATION_PROMPT = (
    "你是正式题库认证审核员，只根据每道题绑定的 source_chunks 审核。"
    "单选题要求题干清晰、正确答案唯一且由来源支持、解析能说明正确依据。错误选项允许来自其他"
    "知识点、常见误解或错误陈述，不要求被当前来源支持；只有错误选项在题干语境下也可能成立、"
    "与正确答案等价或导致真假无法判断时才失败。明显无关但确定错误的干扰项只写入 warnings，"
    "不得判失败。简答题要求参考答案和每个评分点均由来源支持。不得使用外部知识补全。"
    "失败必须返回具体 failed_fields 和中文 reason；通过时 failed_fields 必须为空。"
)


def _apply_distractor_policy(
    decision: CertificationDecision,
    payload: dict[str, Any],
) -> CertificationDecision:
    if decision.verdict != "fail" or payload.get("question_type") != "single_choice":
        return decision
    if set(decision.failed_fields) != {"options"}:
        return decision
    reason = decision.reason
    low_relevance_only = any(
        marker in reason
        for marker in ("无关", "缺乏来源支持", "未在提供的", "source_chunks")
    )
    ambiguity = any(
        marker in reason
        for marker in (
            "多个正确", "多项正确", "也可能成立", "歧义", "等价", "无法判断",
            "正确答案错误", "正确答案不受", "正确答案缺乏",
        )
    )
    if not low_relevance_only or ambiguity:
        return decision
    return CertificationDecision(
        question_id=decision.question_id,
        verdict="pass",
        failed_fields=[],
        reason="",
        warnings=[*decision.warnings, "干扰项与题干关联较弱，但不影响答案唯一性"],
    )


def _semantic_payload(question_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "question_type": payload.get("question_type"),
        "stem": payload.get("stem"),
        "options": payload.get("options") or [],
        "answer": payload.get("answer"),
        "explanation": payload.get("explanation"),
        "rubric": payload.get("rubric") or [],
        "difficulty": payload.get("difficulty"),
        "source_chunks": [
            {
                "source_ref_id": value.get("chunk_id"),
                "content": value.get("content"),
            }
            for value in payload.get("source_chunks") or []
        ],
    }


def _strict_decision_adapter(value: object) -> dict[str, Any]:
    """Keep valid decisions so one malformed sibling does not discard a batch."""

    if not isinstance(value, dict) or set(value) != {"decisions"}:
        raise ModelResponseError("certification output must contain only decisions")
    raw_decisions = value.get("decisions")
    if not isinstance(raw_decisions, list):
        raise ModelResponseError("certification decisions must be a list")
    decisions: list[dict[str, Any]] = []
    for raw in raw_decisions:
        try:
            decision = CertificationDecision.model_validate(raw)
        except ValueError:
            if isinstance(raw, dict):
                logger.warning(
                    "Question certification decision rejected fields=%s",
                    raw.get("failed_fields"),
                )
            continue
        decisions.append(decision.model_dump(mode="json"))
    return {"decisions": decisions}


def certify_question_payloads(
    questions: list[tuple[str, dict[str, Any]]],
    *,
    on_batch_complete: Callable[[dict[str, QuestionCertificationResult]], None] | None = None,
) -> dict[str, QuestionCertificationResult]:
    """Certify formal questions through the sole production certification path."""

    results: dict[str, QuestionCertificationResult] = {}
    eligible: list[tuple[str, dict[str, Any]]] = []
    for question_id, payload in questions:
        issues = deterministic_certification_issues(
            {"candidate_id": question_id, **payload}
        )
        if issues:
            issue = issues[0]
            results[question_id] = QuestionCertificationResult(
                question_id=question_id,
                issue_kind="content_rejected",
                issue_fields=issue.fields,
                issue_reason="题目结构或来源引用不符合正式题库规则",
                report={
                    "rule_version": QUESTION_CERTIFICATION_RULE_VERSION,
                    "deterministic_passed": False,
                    "failed_fields": issue.fields,
                },
            )
        else:
            eligible.append((question_id, payload))

    deterministic_results = {
        question_id: result
        for question_id, result in results.items()
        if result.issue_kind != "valid"
    }
    if deterministic_results and on_batch_complete is not None:
        on_batch_complete(deterministic_results)

    groups = [eligible[index : index + 4] for index in range(0, len(eligible), 4)]
    workers = min(max(1, settings.knowledge_import_review_concurrency), len(groups) or 1)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_certify_group, group): group for group in groups}
        for future in as_completed(futures):
            batch_results = future.result()
            results.update(batch_results)
            if on_batch_complete is not None:
                on_batch_complete(batch_results)
    return results


def _certify_group(
    group: list[tuple[str, dict[str, Any]]],
) -> dict[str, QuestionCertificationResult]:
    pending = {question_id: payload for question_id, payload in group}
    decisions: dict[str, tuple[CertificationDecision, dict[str, Any]]] = {}
    last_error: ModelGatewayError | None = None
    # The gateway already owns 1/3/5 retries for malformed structured output.
    # A second call is only for IDs omitted from an otherwise valid batch.
    for round_number in range(2):
        if not pending:
            break
        try:
            output, metadata = gateway.complete_json(
                model=settings.primary_review_model or settings.primary_llm_model,
                system_prompt=QUESTION_CERTIFICATION_PROMPT,
                payload={
                    "questions": [
                        _semantic_payload(question_id, payload)
                        for question_id, payload in pending.items()
                    ]
                },
                response_adapter=_strict_decision_adapter,
                response_model=CertificationOutput,
                max_output_tokens=max(800, 500 * len(pending)),
            )
            expected = set(pending)
            for raw in output["decisions"]:
                decision = CertificationDecision.model_validate(raw)
                if decision.question_id in expected and decision.question_id not in decisions:
                    decisions[decision.question_id] = (decision, metadata)
            pending = {
                question_id: payload
                for question_id, payload in pending.items()
                if question_id not in decisions
            }
        except ModelGatewayError as exc:
            last_error = exc
            break

    output_results: dict[str, QuestionCertificationResult] = {}
    for question_id, _payload in group:
        saved = decisions.get(question_id)
        if saved is None:
            reason = (
                "认证模型连续返回无效结构，本题尚未完成认证"
                if isinstance(last_error, ModelResponseError)
                else "认证服务暂时不可用，本题尚未完成认证"
            )
            output_results[question_id] = QuestionCertificationResult(
                question_id=question_id,
                issue_kind="certification_service_error",
                issue_fields=["source"],
                issue_reason=reason,
                report={
                    "rule_version": QUESTION_CERTIFICATION_RULE_VERSION,
                    "deterministic_passed": True,
                    "service_error": type(last_error).__name__ if last_error else "missing_decision",
                },
            )
            continue
        decision, metadata = saved
        decision = _apply_distractor_policy(decision, _payload)
        passed = decision.verdict == "pass"
        output_results[question_id] = QuestionCertificationResult(
            question_id=question_id,
            issue_kind="valid" if passed else "content_rejected",
            issue_fields=list(decision.failed_fields),
            issue_reason=decision.reason,
            warnings=decision.warnings,
            report={
                "rule_version": QUESTION_CERTIFICATION_RULE_VERSION,
                "deterministic_passed": True,
                "model_metadata": metadata,
                "failed_fields": list(decision.failed_fields),
                "reason": decision.reason,
                "warnings": decision.warnings,
            },
        )
    return output_results
