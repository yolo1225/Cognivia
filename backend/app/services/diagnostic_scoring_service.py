from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.core.config import settings
from app.models import DiagnosticQuestion
from app.services.llm_service import ModelGatewayError, gateway

RUBRIC_VERSION = "diagnostic-rubric-v1"
PASS_SCORE = 0.6


class RubricCriterion(BaseModel):
    criterion_id: str
    description: str
    max_score: float = Field(gt=0)
    required_concepts: list[str] = Field(default_factory=list)
    equivalent_expressions: list[str] = Field(default_factory=list)


class CriterionScore(BaseModel):
    criterion_id: str
    score: float = Field(ge=0)
    rationale: str


class ShortAnswerScore(BaseModel):
    question_id: str
    criteria: list[CriterionScore]
    matched_points: list[str] = Field(default_factory=list)
    missing_points: list[str] = Field(default_factory=list)
    factual_errors: list[str] = Field(default_factory=list)
    total_score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    ai_comment: str


class ShortAnswerBatch(BaseModel):
    results: list[ShortAnswerScore]

    @model_validator(mode="after")
    def unique_questions(self) -> "ShortAnswerBatch":
        ids = [item.question_id for item in self.results]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate question_id")
        return self


class ShortAnswerBatchEnvelope(BaseModel):
    """Validate the provider envelope while allowing per-question recovery."""

    results: list[dict[str, Any]]


def normalize_rubric(question: DiagnosticQuestion) -> list[RubricCriterion]:
    raw = (question.answer_key_json or {}).get("rubric") or []
    criteria: list[RubricCriterion] = []
    item_count = max(1, len(raw))
    for index, item in enumerate(raw, start=1):
        if isinstance(item, dict):
            concepts = item.get("required_concepts") or []
            if isinstance(concepts, str):
                concepts = [concepts]
            equivalents = item.get("equivalent_expressions") or []
            if isinstance(equivalents, str):
                equivalents = [equivalents]
            criteria.append(
                RubricCriterion(
                    criterion_id=str(item.get("criterion_id") or f"criterion_{index}"),
                    description=str(item.get("description") or " / ".join(map(str, concepts))),
                    max_score=float(item.get("max_score") or 1 / item_count),
                    required_concepts=[str(value) for value in concepts],
                    equivalent_expressions=[str(value) for value in equivalents],
                )
            )
        else:
            text = str(item).strip()
            criteria.append(
                RubricCriterion(
                    criterion_id=f"criterion_{index}",
                    description=f"准确解释：{text}",
                    max_score=1 / item_count,
                    required_concepts=[text] if text else [],
                )
            )
    return criteria


def keyword_precheck(answer: str, criteria: list[RubricCriterion]) -> float:
    if not criteria:
        return 0.0
    normalized = answer.casefold()
    matched = 0.0
    maximum = sum(item.max_score for item in criteria)
    for item in criteria:
        terms = [*item.required_concepts, *item.equivalent_expressions]
        if any(term.casefold() in normalized for term in terms if term.strip()):
            matched += item.max_score
    return round(matched / maximum, 4) if maximum else 0.0


def _fixture_result(items: list[dict[str, Any]]) -> dict[str, Any]:
    results = []
    for item in items:
        criteria = item["rubric"]
        precheck = keyword_precheck(
            item["answer"], [RubricCriterion.model_validate(value) for value in criteria]
        )
        results.append(
            {
                "question_id": item["question_id"],
                "criteria": [
                    {
                        "criterion_id": criterion["criterion_id"],
                        "score": criterion["max_score"] * precheck,
                        "rationale": "fixture semantic scoring",
                    }
                    for criterion in criteria
                ],
                "matched_points": [],
                "missing_points": [],
                "factual_errors": [],
                "total_score": precheck,
                "confidence": 0.8,
                "ai_comment": "已按结构化评分标准完成评分。",
            }
        )
    return {"results": results}


def _adapt_batch_response(
    value: dict[str, Any], rubric_by_question: dict[str, list[dict[str, Any]]] | None = None
) -> dict[str, Any]:
    if "results" in value:
        adapted = value
    elif isinstance(value.get("scores"), list):
        adapted = {**value, "results": value["scores"]}
    elif value.get("question_id"):
        adapted = {"results": [value]}
    else:
        return value
    return adapted


def score_short_answer_batch(
    items: list[tuple[DiagnosticQuestion, str]],
    *,
    domain_display_name: str | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    payload_items = []
    prechecks: dict[str, float] = {}
    for question, answer in items:
        rubric = normalize_rubric(question)
        if not rubric:
            raise ValueError(f"diagnostic_rubric_missing:{question.public_id}")
        prechecks[question.public_id] = keyword_precheck(answer, rubric)
        payload_items.append(
            {
                "question_id": question.public_id,
                "stem": question.stem,
                "answer": answer,
                "rubric": [item.model_dump() for item in rubric],
                "source_summary": (question.answer_key_json or {}).get("reference_answer", ""),
            }
        )

    rubric_by_question = {
        item["question_id"]: item["rubric"] for item in payload_items
    }
    payload_by_question = {item["question_id"]: item for item in payload_items}
    pending_ids = list(payload_by_question)
    validated: dict[str, dict[str, Any]] = {}
    validation_fields: dict[str, list[str]] = {}
    call_metadata: list[dict[str, Any]] = []
    retry_delays = (1, 3, 5)
    display_name = str(domain_display_name or "当前领域").strip()
    system_prompt = (
        f"你是{display_name}的诊断题评分器。必须按 rubric 逐项评分，检查概念关系、因果、"
        "操作目的和事实错误。只堆砌关键词不得获得满分。总分和 confidence 必须在 0 到 1 之间。"
        "每个 results 项必须完整返回 question_id、criteria、matched_points、missing_points、"
        "factual_errors、total_score、confidence、ai_comment；criteria 每项必须包含 criterion_id、"
        "score、rationale。ai_comment 使用简洁中文，不得省略任何字段。"
    )

    for attempt in range(4):
        if not pending_ids:
            break
        current_payload = [payload_by_question[question_id] for question_id in pending_ids]
        try:
            result, metadata = gateway.complete_json(
                model=settings.primary_llm_model,
                system_prompt=system_prompt,
                payload={
                    "questions": current_payload,
                    "rubric_version": RUBRIC_VERSION,
                    "required_output_example": {
                        "results": [
                            {
                                "question_id": "原样返回题目 ID",
                                "criteria": [
                                    {
                                        "criterion_id": "rubric criterion_id",
                                        "score": 0.0,
                                        "rationale": "评分依据",
                                    }
                                ],
                                "matched_points": [],
                                "missing_points": [],
                                "factual_errors": [],
                                "total_score": 0.0,
                                "confidence": 0.0,
                                "ai_comment": "面向学习者的中文评语",
                            }
                        ]
                    },
                    "previous_validation_errors": {
                        question_id: validation_fields.get(question_id, [])
                        for question_id in pending_ids
                    },
                },
                fixture_factory=lambda rows=current_payload: _fixture_result(rows),
                response_model=ShortAnswerBatchEnvelope,
                response_adapter=lambda value: _adapt_batch_response(value, rubric_by_question),
                max_output_tokens=2400,
                # Per-question validation below owns structured retries.
                repair_truncated_output=False,
            )
            call_metadata.append(dict(metadata))
        except ModelGatewayError as exc:
            call_metadata.append(dict(getattr(exc, "metadata", {}) or {}))
            if attempt < len(retry_delays):
                time.sleep(retry_delays[attempt])
                continue
            break

        returned: dict[str, dict[str, Any]] = {}
        for raw in result.get("results") or []:
            question_id = str(raw.get("question_id") or "")
            if question_id in pending_ids and question_id not in returned:
                returned[question_id] = raw

        next_pending: list[str] = []
        for question_id in pending_ids:
            raw = returned.get(question_id)
            if raw is None:
                validation_fields[question_id] = ["missing_result"]
                next_pending.append(question_id)
                continue
            try:
                validated[question_id] = ShortAnswerScore.model_validate(raw).model_dump(
                    mode="json"
                )
                validation_fields.pop(question_id, None)
            except Exception as exc:
                errors = getattr(exc, "errors", lambda: [])()
                validation_fields[question_id] = [
                    ".".join(str(part) for part in error.get("loc", ()))
                    for error in errors
                ] or [type(exc).__name__]
                next_pending.append(question_id)
        pending_ids = next_pending
        if pending_ids and attempt < len(retry_delays):
            time.sleep(retry_delays[attempt])

    controlled: dict[str, dict[str, Any]] = {}
    for question, _answer in items:
        scored = validated.get(question.public_id)
        if scored is None:
            continue
        model_score = float(scored["total_score"])
        precheck = prechecks[question.public_id]
        uncertain = abs(model_score - precheck) > 0.20 or (
            (model_score >= PASS_SCORE) != (precheck >= PASS_SCORE)
        )
        # A semantic synonym may legitimately have a zero literal precheck.
        # Preserve partial credit while keeping disputed answers below the pass gate.
        final_score = (
            min(model_score, max(precheck, PASS_SCORE - 0.05)) if uncertain else model_score
        )
        controlled[question.public_id] = {
            **scored,
            "model_score": round(model_score, 4),
            "precheck_score": round(precheck, 4),
            "total_score": round(final_score, 4),
            "is_correct": final_score >= PASS_SCORE,
            "scoring_uncertain": uncertain,
            "scoring_method": "ai_rubric",
            "rubric_version": RUBRIC_VERSION,
        }
    metadata = {
        "provider_mode": next(
            (item.get("provider_mode") for item in call_metadata if item.get("provider_mode")),
            None,
        ),
        "model_name": next(
            (item.get("model_name") for item in call_metadata if item.get("model_name")),
            settings.primary_llm_model,
        ),
        "tokens_input": sum(int(item.get("tokens_input") or 0) for item in call_metadata),
        "tokens_output": sum(int(item.get("tokens_output") or 0) for item in call_metadata),
        "llm_calls": sum(max(1, int(item.get("attempt") or 1)) for item in call_metadata),
        "calls": call_metadata,
        "failed_question_ids": pending_ids,
        "validation_fields": {
            question_id: validation_fields.get(question_id, []) for question_id in pending_ids
        },
    }
    return controlled, metadata
