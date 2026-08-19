from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.core.config import settings
from app.models import DiagnosticQuestion
from app.services.llm_service import gateway

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


def _adapt_batch_response(value: dict[str, Any]) -> dict[str, Any]:
    if "results" in value:
        return value
    if value.get("question_id"):
        return {"results": [value]}
    return value


def score_short_answer_batch(
    items: list[tuple[DiagnosticQuestion, str]],
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

    result, metadata = gateway.complete_json(
        model=settings.primary_llm_model,
        system_prompt=(
            "你是人工智能应用开发诊断题评分器。必须按 rubric 逐项评分，检查概念关系、"
            "因果、操作目的和事实错误。只堆砌关键词不得获得满分。总分必须在 0 到 1 之间，"
            "评语使用简洁中文。"
        ),
        payload={"questions": payload_items, "rubric_version": RUBRIC_VERSION},
        fixture_factory=lambda: _fixture_result(payload_items),
        response_model=ShortAnswerBatch,
        response_adapter=_adapt_batch_response,
        max_output_tokens=2400,
    )
    by_id = {item["question_id"]: item for item in result["results"]}
    if set(by_id) != {item[0].public_id for item in items}:
        raise ValueError("diagnostic_scoring_incomplete")

    controlled: dict[str, dict[str, Any]] = {}
    for question, _answer in items:
        scored = by_id[question.public_id]
        model_score = float(scored["total_score"])
        precheck = prechecks[question.public_id]
        uncertain = abs(model_score - precheck) > 0.20 or (
            (model_score >= PASS_SCORE) != (precheck >= PASS_SCORE)
        )
        # A semantic synonym may legitimately have a zero literal precheck.
        # Preserve partial credit while keeping disputed answers below the pass gate.
        final_score = min(model_score, max(precheck, PASS_SCORE - 0.05)) if uncertain else model_score
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
    return controlled, metadata
