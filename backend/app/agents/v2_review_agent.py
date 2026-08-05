"""V2 review Agent with dual-model and deterministic evidence cross-checking."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from typing import Literal, Protocol

from pydantic import ValidationError

from app.agents.contracts import (
    ArbitrationResult,
    FactCheck,
    GeneratedResourceArtifact,
    ModelReview,
    ReviewCriterionScores,
    ReviewDecision,
    ReviewIssue,
    ReviewIssueCode,
    ReviewReport,
    ReviewResourceInput,
    ReviewResourceOutput,
    RetrieveKnowledgeInput,
    RetrievedChunk,
    RetrievalPurpose,
)
from app.agents.v2_retrieval_agent import V2KnowledgeRetrievalAgent
from app.agents.v2_observability import record_model_call
from app.core.config import settings
from app.services.llm_service import OpenAICompatibleGateway, gateway


REVIEW_AGENT_NAME = "review_validation_agent_v2"
SYSTEM_PROMPT = (
    "你是 V2 审核校验智能体。独立检查事实准确性、来源可追溯性、难度匹配和核心知识覆盖。"
    "事实与来源结论必须引用输入 evidence 中的 source_ref_id；无法从证据确定时必须明确标记，"
    "不得编造来源。只返回符合 ModelReview JSON Schema 的结构化结果。"
)
PASS_THRESHOLD = 85.0


class V2ReviewError(RuntimeError):
    """Controlled error raised at the V2 review boundary."""


ReviewRole = Literal["primary_review_model", "secondary_review_model"]


class ReviewChannel(Protocol):
    def review(
        self,
        *,
        role: ReviewRole,
        model: str | None,
        resource: GeneratedResourceArtifact,
        request: ReviewResourceInput,
        deterministic_review: ModelReview,
        recheck: bool,
    ) -> ModelReview: ...


class ReviewEvidenceRetriever(Protocol):
    def retrieve(
        self,
        *,
        query_terms: list[str],
        request: ReviewResourceInput,
        resource: GeneratedResourceArtifact,
    ) -> list[RetrievedChunk]: ...


class SuppliedEvidenceRetriever:
    """Re-rank the supplied evidence; production integration may inject a RAG retriever."""

    def retrieve(
        self,
        *,
        query_terms: list[str],
        request: ReviewResourceInput,
        resource: GeneratedResourceArtifact,
    ) -> list[RetrievedChunk]:
        query_tokens = _tokenize(" ".join(query_terms))
        cited_ids = {source.source_ref_id for source in resource.source_refs}

        def rank(chunk: RetrievedChunk) -> tuple[bool, int, float]:
            chunk_tokens = _tokenize(f"{chunk.name} {chunk.content}")
            return (
                chunk.source.source_ref_id in cited_ids,
                len(query_tokens & chunk_tokens),
                chunk.similarity,
            )

        return sorted(request.evidence, key=rank, reverse=True)


class TaskScopedV2ArbitrationRetriever:
    """Re-query V2 candidate evidence with the request created before review.

    ``ReviewResourceInput`` intentionally does not duplicate a profile or retrieval
    plan. The V2 graph composition root must therefore bind this adapter to the
    original retrieval request for the same task; this class never invents those
    inputs from a review payload.
    """

    def __init__(
        self,
        *,
        retrieval_agent: V2KnowledgeRetrievalAgent,
        original_request: RetrieveKnowledgeInput,
    ) -> None:
        self._retrieval_agent = retrieval_agent
        self._original_request = RetrieveKnowledgeInput.model_validate(
            original_request.model_dump(mode="python")
        )

    def retrieve(
        self,
        *,
        query_terms: list[str],
        request: ReviewResourceInput,
        resource: GeneratedResourceArtifact,
    ) -> list[RetrievedChunk]:
        original = self._original_request
        if request.task_id != original.task_id or request.context != original.context:
            raise V2ReviewError("arbitration_retrieval_task_context_mismatch")

        evidence_by_source = {
            chunk.source.source_ref_id: chunk for chunk in request.evidence
        }
        cited_source_ids = [source.source_ref_id for source in resource.source_refs]
        missing_citations = [
            source_id for source_id in cited_source_ids if source_id not in evidence_by_source
        ]
        if missing_citations:
            raise V2ReviewError("arbitration_retrieval_unknown_cited_source")

        cited_knowledge_ids = _ordered_unique(
            evidence_by_source[source_id].knowledge_id for source_id in cited_source_ids
        )
        plan = original.retrieval_plan.model_copy(
            update={
                "priority_knowledge_ids": _ordered_unique(
                    [*cited_knowledge_ids, *original.retrieval_plan.priority_knowledge_ids]
                ),
                "query_terms": _ordered_unique(
                    [*original.retrieval_plan.query_terms, *query_terms]
                )[:30],
                # Reserve one slot for evidence beyond the resource's cited sources.
                "n_results": min(12, max(original.retrieval_plan.n_results, len(cited_knowledge_ids) + 1)),
            }
        )
        refreshed = self._retrieval_agent.execute(
            RetrieveKnowledgeInput(
                task_id=original.task_id,
                context=original.context,
                profile=original.profile,
                retrieval_plan=plan,
                revision_plan=original.revision_plan,
                purpose=RetrievalPurpose.SOURCE_VERIFICATION,
            )
        )
        refreshed_source_ids = {chunk.source.source_ref_id for chunk in refreshed.chunks}
        if not set(cited_source_ids).issubset(refreshed_source_ids):
            raise V2ReviewError("arbitration_retrieval_missing_cited_evidence")
        return refreshed.chunks


class OpenAICompatibleReviewChannel:
    def __init__(self, model_gateway: OpenAICompatibleGateway = gateway) -> None:
        self._gateway = model_gateway

    def review(
        self,
        *,
        role: ReviewRole,
        model: str | None,
        resource: GeneratedResourceArtifact,
        request: ReviewResourceInput,
        deterministic_review: ModelReview,
        recheck: bool,
    ) -> ModelReview:
        result, metadata = self._gateway.complete_json(
            model=model,
            system_prompt=SYSTEM_PROMPT,
            payload={
                "review_role": role,
                "recheck": recheck,
                "resource": resource.model_dump(mode="json"),
                "requirements": request.requirements.model_dump(mode="json"),
                "evidence": [item.model_dump(mode="json") for item in request.evidence],
                "output_schema": ModelReview.model_json_schema(),
            },
            fixture_factory=lambda: deterministic_review.model_dump(mode="json"),
            response_model=ModelReview,
            # The role and selected model are composition-root metadata, not a
            # judgment delegated to the model.  Compatible providers sometimes
            # omit these two schema fields even when their assessment payload is
            # otherwise valid; bind them at this boundary before strict contract
            # validation rather than retrying a correct assessment indefinitely.
            response_adapter=lambda payload: _adapt_model_review_payload(
                payload,
                role=role,
                model_name=model,
            ),
        )
        record_model_call(metadata, role=role, recheck=recheck)
        reviewed = ModelReview.model_validate(result)
        expected_model_name = model or metadata.get("model_name") or "deterministic-review"
        return reviewed.model_copy(
            update={"model_role": role, "model_name": str(expected_model_name)}
        )


def _adapt_model_review_payload(
    payload: dict[str, object],
    *,
    role: ReviewRole,
    model_name: str | None,
) -> dict[str, object]:
    """Normalize provider-neutral review aliases without weakening V2 validation.

    The gateway still validates the result against ``ModelReview``.  This adapter
    only supplies metadata the application already knows and accepts a small set
    of common OpenAI-compatible aliases; it never manufactures scores, factual
    judgments, evidence, or a pass/fail decision.
    """
    if not isinstance(payload, dict):
        return payload

    candidate: dict[str, object] = dict(payload)
    for wrapper in ("review", "result", "data"):
        nested = candidate.get(wrapper)
        if isinstance(nested, dict) and any(
            key in nested for key in ("scores", "review_scores", "fact_checks")
        ):
            candidate = dict(nested)
            break

    if "scores" not in candidate and isinstance(candidate.get("review_scores"), dict):
        candidate["scores"] = candidate.pop("review_scores")
    scores = candidate.get("scores")
    if isinstance(scores, dict):
        normalized_scores = dict(scores)
        aliases = {
            "accuracy": "factual_accuracy",
            "factual_score": "factual_accuracy",
            "traceability": "source_traceability",
            "source_score": "source_traceability",
            "difficulty": "difficulty_match",
            "difficulty_score": "difficulty_match",
            "coverage": "core_knowledge_coverage",
            "coverage_score": "core_knowledge_coverage",
        }
        for source, target in aliases.items():
            if target not in normalized_scores and source in normalized_scores:
                normalized_scores[target] = normalized_scores.pop(source)
        candidate["scores"] = normalized_scores

    checks = candidate.get("fact_checks")
    if isinstance(checks, list):
        adapted_checks: list[object] = []
        for check in checks:
            if not isinstance(check, dict):
                adapted_checks.append(check)
                continue
            normalized_check = dict(check)
            if "source_ref_ids" not in normalized_check:
                for alias in ("source_ids", "evidence_ids", "sources"):
                    if alias in normalized_check:
                        source_ids = normalized_check.pop(alias)
                        normalized_check["source_ref_ids"] = (
                            [source_ids] if isinstance(source_ids, str) else source_ids
                        )
                        break
            elif isinstance(normalized_check["source_ref_ids"], str):
                normalized_check["source_ref_ids"] = [normalized_check["source_ref_ids"]]
            if "supported" not in normalized_check and "is_supported" in normalized_check:
                normalized_check["supported"] = normalized_check.pop("is_supported")
            if "determinable" not in normalized_check and "is_determinable" in normalized_check:
                normalized_check["determinable"] = normalized_check.pop("is_determinable")
            adapted_checks.append(normalized_check)
        candidate["fact_checks"] = adapted_checks

    candidate["model_role"] = role
    candidate["model_name"] = model_name or str(candidate.get("model_name") or role)
    return candidate


class V2ReviewValidationAgent:
    """Formal V2 boundary for independent dual-channel resource review."""

    name = REVIEW_AGENT_NAME
    system_prompt = SYSTEM_PROMPT

    def __init__(
        self,
        channel: ReviewChannel | None = None,
        evidence_retriever: ReviewEvidenceRetriever | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._channel = channel or OpenAICompatibleReviewChannel()
        self._evidence_retriever = evidence_retriever or SuppliedEvidenceRetriever()
        self._logger = logger or logging.getLogger(__name__)

    def execute(self, request: ReviewResourceInput) -> ReviewResourceOutput:
        if not isinstance(request, ReviewResourceInput):
            self._logger.warning("review_rejected error_code=invalid_review_input_type")
            raise V2ReviewError("invalid_review_input_type")
        try:
            validated = ReviewResourceInput.model_validate(request.model_dump(mode="python"))
            reports = [self._review_resource(resource, validated) for resource in validated.resources]
            output = ReviewResourceOutput(task_id=validated.task_id, reports=reports)
        except V2ReviewError:
            self._log_failure(request, "review_policy_rejected")
            raise
        except ValidationError as exc:
            self._log_failure(request, "invalid_review_resource_output")
            raise V2ReviewError("invalid_review_resource_output") from exc
        except Exception as exc:
            self._log_failure(request, "review_execution_failed")
            raise V2ReviewError("review_execution_failed") from exc

        self._logger.info(
            "review_completed task_id=%s report_count=%s manual_review_required=%s",
            output.task_id,
            len(output.reports),
            any(report.manual_review_required for report in output.reports),
        )
        return output

    def _review_resource(
        self,
        resource: GeneratedResourceArtifact,
        request: ReviewResourceInput,
    ) -> ReviewReport:
        primary, secondary = self._review_pair(resource, request, recheck=False)
        disagreement = _reviews_disagree(primary, secondary)
        final_primary, final_secondary = primary, secondary
        query_terms: list[str] = []
        refreshed_evidence: list[RetrievedChunk] = []

        if disagreement:
            query_terms = _arbitration_query_terms(resource, request)
            refreshed_evidence = self._evidence_retriever.retrieve(
                query_terms=query_terms,
                request=request,
                resource=resource,
            )
            cited_ids = {source.source_ref_id for source in resource.source_refs}
            refreshed_ids = {chunk.source.source_ref_id for chunk in refreshed_evidence}
            if not refreshed_evidence or not cited_ids.issubset(refreshed_ids):
                raise V2ReviewError("arbitration_retrieval_missing_cited_evidence")
            recheck_request = request.model_copy(update={"evidence": refreshed_evidence})
            final_primary, final_secondary = self._review_pair(
                resource, recheck_request, recheck=True
            )

        disagreement_remains = disagreement and _reviews_disagree(
            final_primary, final_secondary
        )
        final_scores = _conservative_scores(final_primary, final_secondary)
        issues = _unique_issues([*final_primary.issues, *final_secondary.issues])
        decision = _review_decision(
            final_primary, final_secondary, final_scores, disagreement_remains
        )
        evidence_ref_ids = sorted(
            {
                source_id
                for review in (final_primary, final_secondary)
                for fact_check in review.fact_checks
                for source_id in fact_check.source_ref_ids
            }
        )
        if not evidence_ref_ids:
            evidence_ref_ids = sorted(
                source.source_ref_id for source in resource.source_refs
            )

        return ReviewReport(
            resource_type=resource.resource_type,
            primary_review=primary,
            secondary_review=secondary,
            final_scores=final_scores,
            arbitration=ArbitrationResult(
                required=disagreement,
                retrieval_performed=disagreement,
                query_terms=query_terms,
                additional_source_ref_ids=sorted(
                    {
                        chunk.source.source_ref_id
                        for chunk in refreshed_evidence
                        if chunk.source.source_ref_id
                        not in {source.source_ref_id for source in resource.source_refs}
                    }
                ),
                primary_recheck=final_primary if disagreement else None,
                secondary_recheck=final_secondary if disagreement else None,
                disagreement_remains=disagreement_remains,
            ),
            issues=issues,
            evidence_ref_ids=evidence_ref_ids,
            decision=decision,
            passed=decision == ReviewDecision.PASSED,
            manual_review_required=decision == ReviewDecision.MANUAL_REVIEW_REQUIRED,
        )

    def _review_pair(
        self,
        resource: GeneratedResourceArtifact,
        request: ReviewResourceInput,
        *,
        recheck: bool,
    ) -> tuple[ModelReview, ModelReview]:
        calls: tuple[tuple[ReviewRole, str | None], ...] = (
            ("primary_review_model", settings.primary_review_model),
            ("secondary_review_model", settings.secondary_review_model),
        )

        def call(item: tuple[ReviewRole, str | None]) -> ModelReview:
            role, model = item
            deterministic = _deterministic_review(resource, request, role, model)
            reviewed = self._channel.review(
                role=role,
                model=model,
                resource=resource,
                request=request,
                deterministic_review=deterministic,
                recheck=recheck,
            )
            return _cross_validate(reviewed, deterministic, request)

        contexts = [copy_context() for _ in calls]
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(context.run, call, item)
                for context, item in zip(contexts, calls, strict=True)
            ]
            results = [future.result() for future in futures]
        return results[0], results[1]

    def _log_failure(self, request: ReviewResourceInput, error_code: str) -> None:
        self._logger.warning(
            "review_failed task_id=%s error_code=%s",
            getattr(request, "task_id", "unknown"),
            error_code,
        )


def _tokenize(text: str) -> set[str]:
    lowered = text.lower()
    words = set(re.findall(r"[a-z0-9_]+", lowered))
    cjk = "".join(re.findall(r"[\u4e00-\u9fff]", lowered))
    words.update(cjk[index : index + 3] for index in range(max(0, len(cjk) - 2)))
    return {token for token in words if token}


def _ordered_unique(values: Iterable[object]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value).strip()
        if item and item not in seen:
            result.append(item)
            seen.add(item)
    return result


def _source_overlap(content: str, evidence: list[RetrievedChunk]) -> float:
    content_tokens = _tokenize(content)
    evidence_tokens = _tokenize(" ".join(chunk.content for chunk in evidence))
    if not content_tokens or not evidence_tokens:
        return 0.0
    return len(content_tokens & evidence_tokens) / len(content_tokens)


def _deterministic_review(
    resource: GeneratedResourceArtifact,
    request: ReviewResourceInput,
    role: ReviewRole,
    model: str | None,
) -> ModelReview:
    evidence_by_source = {chunk.source.source_ref_id: chunk for chunk in request.evidence}
    cited_ids = {source.source_ref_id for source in resource.source_refs}
    source_valid = cited_ids.issubset(evidence_by_source)
    overlap = _source_overlap(
        resource.content_md, [evidence_by_source[source_id] for source_id in cited_ids]
    )
    factual = min(100.0, 70.0 + overlap * 100) if source_valid else 0.0
    traceability = 100.0 if source_valid and cited_ids else 0.0
    difficulty_delta = abs(resource.difficulty - request.requirements.target_difficulty)
    difficulty = max(0.0, 100.0 - difficulty_delta * 25.0)
    covered_ids = {evidence_by_source[source_id].knowledge_id for source_id in cited_ids}
    required_ids = set(request.requirements.required_knowledge_ids)
    coverage = 100.0 * len(covered_ids & required_ids) / max(1, len(required_ids))
    scores = ReviewCriterionScores(
        factual_accuracy=round(factual, 2),
        source_traceability=traceability,
        difficulty_match=difficulty,
        core_knowledge_coverage=round(coverage, 2),
    )
    issues: list[ReviewIssue] = []
    if not source_valid:
        issues.append(
            ReviewIssue(
                code=ReviewIssueCode.MISSING_SOURCE,
                section="知识来源",
                description="资源引用了审核证据之外的来源。",
                suggested_revision="仅保留本次检索证据中的来源引用。",
            )
        )
    if coverage < 90:
        issues.append(
            ReviewIssue(
                code=ReviewIssueCode.MISSING_KNOWLEDGE,
                section="核心知识",
                knowledge_ids=sorted(required_ids - covered_ids),
                description="资源未覆盖全部必需知识点。",
                suggested_revision="补充缺失知识点并绑定可追溯来源。",
            )
        )
    fact_check = FactCheck(
        claim=f"资源内容与 {len(cited_ids)} 个引用来源一致。",
        supported=source_valid and overlap > 0,
        source_ref_ids=sorted(cited_ids) if source_valid else [],
        reason="基于资源文本与检索证据的确定性重叠检查。",
    )
    passed = all(value >= PASS_THRESHOLD for value in scores.model_dump().values())
    return ModelReview(
        model_role=role,
        model_name=model or "deterministic-review",
        scores=scores,
        passed=passed,
        fact_checks=[fact_check],
        issues=issues,
    )


def _cross_validate(
    reviewed: ModelReview,
    deterministic: ModelReview,
    request: ReviewResourceInput,
) -> ModelReview:
    valid_source_ids = {chunk.source.source_ref_id for chunk in request.evidence}
    fact_checks = [
        fact_check.model_copy(
            update={
                "source_ref_ids": [
                    source_id
                    for source_id in fact_check.source_ref_ids
                    if source_id in valid_source_ids
                ]
            }
        )
        for fact_check in reviewed.fact_checks
    ]
    reviewed_values = reviewed.scores.model_dump()
    deterministic_values = deterministic.scores.model_dump()
    adjusted = {
        key: (
            round((reviewed_values[key] * 0.6) + (deterministic_values[key] * 0.4), 2)
            if abs(reviewed_values[key] - deterministic_values[key]) > 25
            else reviewed_values[key]
        )
        for key in reviewed_values
    }
    unsupported_facts = _unsupported_fact_checks(fact_checks)
    if unsupported_facts:
        # A deterministic, negative fact check is stronger evidence than a model's
        # aggregate self-score.  Keep the report quantitative while ensuring a
        # resource with a known unsupported claim can never pass to a learner.
        adjusted["factual_accuracy"] = min(adjusted["factual_accuracy"], PASS_THRESHOLD - 1)
    scores = ReviewCriterionScores(**adjusted)
    issues = list(reviewed.issues)
    if unsupported_facts:
        issues.append(
            ReviewIssue(
                code=ReviewIssueCode.UNSUPPORTED_CLAIM,
                section="事实核验",
                description="审核模型标记了无法由当前证据支持的确定性事实。",
                suggested_revision="删除、修正该事实，或补充可追溯的知识库证据后重新审核。",
            )
        )
    passed = (
        reviewed.passed
        and not unsupported_facts
        and all(value >= PASS_THRESHOLD for value in adjusted.values())
    )
    return reviewed.model_copy(
        update={
            "scores": scores,
            "passed": passed,
            "fact_checks": fact_checks,
            "issues": _unique_issues(issues),
        }
    )


def _review_average(review: ModelReview) -> float:
    values = review.scores.model_dump().values()
    return sum(values) / 4


def _unsupported_fact_checks(fact_checks: Iterable[FactCheck]) -> list[FactCheck]:
    return [
        fact_check
        for fact_check in fact_checks
        if fact_check.determinable and fact_check.supported is False
    ]


def _has_unsupported_fact(review: ModelReview) -> bool:
    return bool(_unsupported_fact_checks(review.fact_checks))


def _reviews_disagree(primary: ModelReview, secondary: ModelReview) -> bool:
    return abs(_review_average(primary) - _review_average(secondary)) > 10 or (
        primary.passed != secondary.passed
    ) or (_has_unsupported_fact(primary) != _has_unsupported_fact(secondary))


def _conservative_scores(
    primary: ModelReview, secondary: ModelReview
) -> ReviewCriterionScores:
    first = primary.scores.model_dump()
    second = secondary.scores.model_dump()
    return ReviewCriterionScores(**{key: min(first[key], second[key]) for key in first})


def _review_decision(
    primary: ModelReview,
    secondary: ModelReview,
    scores: ReviewCriterionScores,
    disagreement_remains: bool,
) -> ReviewDecision:
    if disagreement_remains:
        return ReviewDecision.MANUAL_REVIEW_REQUIRED
    if (
        primary.passed
        and secondary.passed
        and not _has_unsupported_fact(primary)
        and not _has_unsupported_fact(secondary)
    ):
        return ReviewDecision.PASSED
    if scores.source_traceability == 0 or scores.factual_accuracy < 50:
        return ReviewDecision.REJECTED
    return ReviewDecision.REVISION_REQUIRED


def _arbitration_query_terms(
    resource: GeneratedResourceArtifact, request: ReviewResourceInput
) -> list[str]:
    terms = [*request.requirements.required_knowledge_ids]
    title = resource.structured_content.title.strip()
    if title and title not in terms:
        terms.append(title)
    return terms[:30] or [resource.resource_type.value]


def _unique_issues(issues: list[ReviewIssue]) -> list[ReviewIssue]:
    unique: list[ReviewIssue] = []
    seen: set[tuple[str, str, str]] = set()
    for issue in issues:
        key = (issue.code.value, issue.section, issue.description)
        if key not in seen:
            seen.add(key)
            unique.append(issue)
    return unique
