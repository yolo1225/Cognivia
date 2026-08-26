from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from functools import partial
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    DiagnosticQuestion,
    KnowledgeImportCandidate,
    KnowledgeImportRun,
    KnowledgeItem,
)
from app.rag.candidate_chunker import CHUNKER_VERSION
from app.services.knowledge_import_batch_service import (
    execute_json_batch,
    pack_by_tokens,
    prepare_batch,
    run_parallel,
)


QUESTION_CERTIFICATION_RULE_VERSION = "question-cert-v1"
_SPACE_RE = re.compile(r"\s+")


class CertificationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    fields: list[str] = []
    reason: str = ""


class CertificationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    verdict: Literal["pass", "fail"]
    failed_fields: list[str] = []
    reason: str = ""


class CertificationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[CertificationDecision]


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


def _adapt_certification_output(result: object) -> dict[str, Any]:
    raw = result.get("decisions") if isinstance(result, dict) else []
    decisions: list[dict[str, Any]] = []
    for value in raw or []:
        if not isinstance(value, dict):
            continue
        verdict = value.get("verdict") or value.get("decision")
        if verdict in {True, "accepted", "certified", "supported", "yes"}:
            verdict = "pass"
        elif verdict in {False, "rejected", "unsupported", "no"}:
            verdict = "fail"
        decisions.append(
            {
                "question_id": value.get("question_id") or value.get("id"),
                "verdict": verdict,
                "failed_fields": value.get("failed_fields") or value.get("fields") or [],
                "reason": str(value.get("reason") or "")[:300],
            }
        )
    return {"decisions": decisions}


def _review_payload(candidate: KnowledgeImportCandidate) -> dict[str, Any]:
    payload = dict(candidate.payload_json or {})
    return {
        "question_id": candidate.public_id,
        "knowledge_id": payload.get("knowledge_candidate_id"),
        "question_type": payload.get("question_type"),
        "stem": payload.get("stem"),
        "options": payload.get("options") or [],
        "answer": payload.get("answer"),
        "rubric": payload.get("rubric") or [],
        "explanation": payload.get("explanation"),
        "quiz_level": payload.get("quiz_level"),
        "difficulty": payload.get("difficulty"),
        "evidence_quotes": payload.get("evidence_quotes") or [],
        "source_chunks": [
            {
                "source_ref_id": value.get("chunk_id"),
                "source_locator": value.get("source_locator"),
                "knowledge_id": value.get("knowledge_id"),
                "content": value.get("content"),
            }
            for value in payload.get("source_chunks") or []
        ],
    }


def _run_review_channel(
    db: Session,
    run: KnowledgeImportRun,
    candidates: list[KnowledgeImportCandidate],
    *,
    model_name: str | None,
    model_role: str,
    round_number: int,
) -> dict[str, CertificationDecision]:
    records = [_review_payload(candidate) for candidate in candidates]
    groups = pack_by_tokens(records, max_records=4, target_tokens=6000)
    prepared: list[tuple[int, list[dict[str, Any]]]] = []
    for index, group in enumerate(groups):
        payload = {"questions": group}
        batch = prepare_batch(
            db,
            run,
            step=f"question_certification_{model_role}_{round_number}",
            batch_key=f"{model_role}_{round_number}_{index}",
            payload=payload,
            model_name=model_name,
            prompt_version=QUESTION_CERTIFICATION_RULE_VERSION,
        )
        prepared.append((batch.id, group))
    db.commit()
    jobs = [
        partial(
            execute_json_batch,
            batch_id,
            model=model_name,
            system_prompt=(
                "你是正式题库独立认证审核员。逐题对照题目绑定的 source_chunks，分别检查题干、正确答案、"
                "所有选项、解析和简答 rubric 是否完全由这些 Chunk 支持，是否存在歧义、来源外结论或"
                "错误难度。不得使用外部知识补全，不得因题量要求放宽。每题必须返回 verdict=pass/fail；"
                "失败时 failed_fields 只能列出 stem/options/answer/explanation/rubric/difficulty 中的具体字段。"
            ),
            payload={"questions": group},
            response_model=CertificationOutput,
            response_adapter=_adapt_certification_output,
            max_output_tokens=1400,
            role="review",
        )
        for batch_id, group in prepared
    ]
    results = run_parallel(jobs, max_workers=settings.knowledge_import_review_concurrency)
    output: dict[str, CertificationDecision] = {}
    for result, (_, group) in zip(results, prepared, strict=True):
        expected_ids = {str(item["question_id"]) for item in group}
        if isinstance(result, Exception):
            for question_id in expected_ids:
                output[question_id] = CertificationDecision(
                    question_id=question_id,
                    verdict="fail",
                    failed_fields=["review_channel"],
                    reason=type(result).__name__,
                )
            continue
        decisions = {
            str(value.get("question_id")): CertificationDecision.model_validate(value)
            for value in result.get("decisions") or []
            if str(value.get("question_id") or "") in expected_ids
        }
        for question_id in expected_ids:
            output[question_id] = decisions.get(
                question_id,
                CertificationDecision(
                    question_id=question_id,
                    verdict="fail",
                    failed_fields=["review_response"],
                    reason="missing_decision",
                ),
            )
    return output


def certify_question_candidates(
    db: Session,
    run: KnowledgeImportRun,
    candidates: list[KnowledgeImportCandidate],
    *,
    round_number: int,
) -> tuple[set[str], dict[str, list[str]]]:
    deterministic_failures: dict[str, list[str]] = {}
    eligible: list[KnowledgeImportCandidate] = []
    for candidate in candidates:
        payload = dict(candidate.payload_json or {})
        issues = deterministic_certification_issues(
            {"candidate_id": candidate.public_id, **payload}
        )
        if issues:
            deterministic_failures[candidate.public_id] = issues[0].fields
        else:
            eligible.append(candidate)

    certification_model = settings.primary_review_model or settings.primary_llm_model
    model_results = _run_review_channel(
        db,
        run,
        eligible,
        model_name=certification_model,
        model_role="certifier",
        round_number=round_number,
    )
    certified: set[str] = set()
    failed_fields = dict(deterministic_failures)
    certified_at = datetime.now(UTC).replace(tzinfo=None)
    for candidate in candidates:
        payload = dict(candidate.payload_json or {})
        model_result = model_results.get(candidate.public_id)
        passed = (
            candidate.public_id not in deterministic_failures
            and model_result is not None
            and model_result.verdict == "pass"
        )
        combined_fields = list(
            dict.fromkeys(
                [
                    *failed_fields.get(candidate.public_id, []),
                    *(model_result.failed_fields if model_result else []),
                ]
            )
        )
        report = {
            "rule_version": QUESTION_CERTIFICATION_RULE_VERSION,
            "deterministic_passed": candidate.public_id not in deterministic_failures,
            "model_role": {
                "question_certification_model": {
                    "model_name": certification_model,
                    "passed": bool(model_result and model_result.verdict == "pass"),
                    "failed_fields": model_result.failed_fields if model_result else [],
                    "reason": model_result.reason if model_result else "not_run",
                },
            },
            "failed_fields": combined_fields,
            "source_content_hash": payload.get("source_content_hash"),
            "certified_at": certified_at.isoformat() if passed else None,
        }
        payload["certification_status"] = "certified" if passed else "rejected"
        payload["certification_rule_version"] = QUESTION_CERTIFICATION_RULE_VERSION
        payload["certification_report"] = report
        payload["certified_at"] = report["certified_at"]
        candidate.payload_json = payload
        if passed:
            certified.add(candidate.public_id)
        else:
            failed_fields[candidate.public_id] = combined_fields or ["model_review"]
    db.flush()
    return certified, failed_fields
