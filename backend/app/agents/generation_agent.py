"""V10 content generation Agent with structured generation and deterministic rendering."""

from __future__ import annotations

import hashlib
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from collections.abc import Callable
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agents.contracts import (
    GenerateResourceInput,
    GenerateResourceOutput,
    GeneratedResourceArtifact,
    GradedQuizContent,
    LectureContent,
    PracticeGuideContent,
    QuestionType,
    QuizQuestion,
    ResourceType,
    SourceRef,
    StructuredResourceContent,
    structured_source_ref_ids,
)
from app.agents.observability import record_model_call
from app.agents.claim_policy import sanitize_deterministic_text
from app.agents.prompt_registry import get_prompt
from app.agents.review_claim_manifest import build_review_claims
from app.agents.domain_evidence_policy import evidence_capability_payload
from app.agents.prompt_budget import bounded_text, estimate_tokens
from app.core.config import settings
from app.services.llm_service import (
    ModelCallError,
    ModelResponseError,
    OpenAICompatibleGateway,
    gateway,
)
from app.services.question_bank_service import (
    QuestionBankError,
    build_graded_quiz_from_question_bank,
    quiz_revision_question_indexes,
)


GENERATION_AGENT_NAME = "content_generation_agent_v3"
SYSTEM_PROMPT = get_prompt("generation")
SOURCE_REPAIR_PROMPT = get_prompt("generation.source_repair")
REVISION_PROMPT = get_prompt("generation.revision")
MAX_SOURCE_REPAIR_ATTEMPTS = 1
_QUIZ_UNSUPPORTED_DISTRACTOR_RE = re.compile(
    r"(?:证据|材料|文档|原文|RFC).{0,24}(?:未提到|未出现|未说明|未声明)|"
    r"(?:未在|没有在).{0,24}(?:证据|材料|文档|原文).{0,12}(?:出现|说明|声明)|"
    r"(?:故|因此|所以)(?:应)?(?:排除|仅选|只选|不选)"
)


class GenerationError(RuntimeError):
    """Controlled error raised at the active generation boundary."""

    def __init__(
        self,
        code: str,
        *,
        field_paths: list[str] | None = None,
        violations: list[dict[str, object]] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.field_paths = [str(path)[:200] for path in (field_paths or [])][:20]
        self.violations = [dict(item) for item in (violations or [])][:20]


class GeneratedContentResponse(BaseModel):
    # Compatible providers echo request-payload keys (``source_violations``,
    # ``policy_violations``) back alongside the requested output.  These are
    # input context, not part of the contract, so tolerate and drop them rather
    # than burning the bounded validation-retry budget on an extra-field echo.
    model_config = ConfigDict(extra="ignore")

    structured_content: StructuredResourceContent
    difficulty: int


class RevisionFieldPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=512)
    value: str | None = Field(default=None, max_length=6000)


class RevisionPatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patches: list[RevisionFieldPatch] = Field(default_factory=list, max_length=30)


class LectureGenerationResponse(BaseModel):
    """Internal response shape for a lecture-only model call."""

    model_config = ConfigDict(extra="ignore")
    structured_content: LectureContent
    difficulty: int


class PracticeGuideGenerationResponse(BaseModel):
    """Internal response shape for a practice-guide-only model call."""

    model_config = ConfigDict(extra="ignore")
    structured_content: PracticeGuideContent
    difficulty: int


class GradedQuizGenerationResponse(BaseModel):
    """Internal response shape for a graded-quiz-only model call."""

    model_config = ConfigDict(extra="ignore")
    structured_content: GradedQuizContent
    difficulty: int


GenerationResponseModel = (
    type[LectureGenerationResponse]
    | type[PracticeGuideGenerationResponse]
    | type[GradedQuizGenerationResponse]
)


def _response_model_for(resource_type: ResourceType) -> GenerationResponseModel:
    return {
        ResourceType.LECTURE: LectureGenerationResponse,
        ResourceType.PRACTICE_GUIDE: PracticeGuideGenerationResponse,
        ResourceType.GRADED_QUIZ: GradedQuizGenerationResponse,
    }[resource_type]


def _max_output_tokens_for(resource_type: ResourceType) -> int:
    if resource_type == ResourceType.GRADED_QUIZ:
        return settings.graded_quiz_max_output_tokens
    return settings.generation_max_output_tokens


class StructuredContentGenerator(Protocol):
    def generate(
        self,
        request: GenerateResourceInput,
        resource_type: ResourceType,
        allowed_sources: list[SourceRef],
    ) -> GeneratedContentResponse: ...


class OpenAICompatibleStructuredGenerator:
    def __init__(
        self,
        *,
        model: str | None = None,
        model_gateway: OpenAICompatibleGateway = gateway,
        evidence_capabilities_by_knowledge: dict[str, list[str]] | None = None,
    ) -> None:
        self._model = model if model is not None else settings.primary_llm_model
        self._gateway = model_gateway
        self._evidence_capabilities_by_knowledge = evidence_capabilities_by_knowledge or {}

    def _payload(self, *args: Any, **kwargs: Any) -> dict[str, object]:
        return _generation_payload(
            *args,
            **kwargs,
            evidence_capabilities_by_knowledge=self._evidence_capabilities_by_knowledge,
        )

    def generate(
        self,
        request: GenerateResourceInput,
        resource_type: ResourceType,
        allowed_sources: list[SourceRef],
    ) -> GeneratedContentResponse:
        fixture = _fixture_response(request, resource_type, allowed_sources)
        response_model = _response_model_for(resource_type)
        result, metadata = self._gateway.complete_json(
            model=self._model,
            system_prompt=SYSTEM_PROMPT,
            payload=self._payload(
                request, resource_type, allowed_sources, response_model=response_model
            ),
            fixture_factory=lambda: fixture.model_dump(mode="json"),
            response_model=response_model,
            max_output_tokens=_max_output_tokens_for(resource_type),
        )
        record_model_call(
            metadata,
            role="generation_model",
            resource_type=resource_type.value,
        )
        return GeneratedContentResponse.model_validate(result)

    def revise(
        self,
        request: GenerateResourceInput,
        resource_type: ResourceType,
        allowed_sources: list[SourceRef],
        candidate: GeneratedContentResponse,
    ) -> RevisionPatchResponse:
        revision_plan = request.requirements.revision_plan
        if revision_plan is None:
            raise GenerationError("revision_plan_required")
        response_model = RevisionPatchResponse
        field_paths = revision_plan.field_paths_by_resource.get(resource_type, [])
        result, metadata = self._gateway.complete_json(
            model=self._model,
            system_prompt=REVISION_PROMPT,
            payload=self._payload(
                request,
                resource_type,
                allowed_sources,
                candidate=candidate,
                correction_attempt=revision_plan.revision_count,
                response_model=response_model,
            ),
            fixture_factory=lambda: _revision_patch_fixture(candidate, field_paths).model_dump(
                mode="json"
            ),
            response_model=response_model,
            max_output_tokens=min(2000, _max_output_tokens_for(resource_type)),
        )
        record_model_call(
            metadata,
            role="generation_model",
            resource_type=resource_type.value,
            correction_attempt=revision_plan.revision_count,
            correction_kind="field_revision",
        )
        return RevisionPatchResponse.model_validate(result)

    def repair(
        self,
        request: GenerateResourceInput,
        resource_type: ResourceType,
        allowed_sources: list[SourceRef],
        candidate: GeneratedContentResponse,
        violations: list[dict[str, str]],
        attempt: int,
    ) -> GeneratedContentResponse:
        fixture = _fixture_response(request, resource_type, allowed_sources)
        response_model = _response_model_for(resource_type)
        result, metadata = self._gateway.complete_json(
            model=self._model,
            system_prompt=SOURCE_REPAIR_PROMPT,
            payload=self._payload(
                request,
                resource_type,
                allowed_sources,
                candidate=candidate,
                violations=violations,
                correction_attempt=attempt,
                response_model=response_model,
            ),
            fixture_factory=lambda: fixture.model_dump(mode="json"),
            response_model=response_model,
            max_output_tokens=_max_output_tokens_for(resource_type),
        )
        record_model_call(
            metadata,
            role="generation_model",
            resource_type=resource_type.value,
            correction_attempt=attempt,
        )
        return GeneratedContentResponse.model_validate(result)

class ContentGenerationAgent:
    """Formal V10 boundary for personalized resource generation."""

    name = GENERATION_AGENT_NAME
    system_prompt = SYSTEM_PROMPT

    def __init__(
        self,
        generator: StructuredContentGenerator | None = None,
        logger: logging.Logger | None = None,
        renderer: Callable[[StructuredResourceContent, list[SourceRef]], str] | None = None,
        evidence_capabilities_by_knowledge: dict[str, list[str]] | None = None,
    ) -> None:
        self._evidence_capabilities_by_knowledge = evidence_capabilities_by_knowledge or {}
        self._generator = generator or OpenAICompatibleStructuredGenerator(
            evidence_capabilities_by_knowledge=self._evidence_capabilities_by_knowledge
        )
        self._logger = logger or logging.getLogger(__name__)
        self._renderer = renderer

    def execute(self, request: GenerateResourceInput) -> GenerateResourceOutput:
        return self._execute(request, {}, {})

    def revise(
        self,
        request: GenerateResourceInput,
        candidates: list[GeneratedResourceArtifact],
        audited_claims_by_type: dict[ResourceType, dict[str, list[str]]] | None = None,
    ) -> GenerateResourceOutput:
        if request.requirements.revision_plan is None:
            raise GenerationError("revision_plan_required")
        return self._execute(
            request,
            {candidate.resource_type: candidate for candidate in candidates},
            audited_claims_by_type or {},
        )

    def converge(
        self,
        request: GenerateResourceInput,
        candidates: list[GeneratedResourceArtifact],
        removable_claims_by_type: dict[ResourceType, dict[str, list[str]]],
    ) -> GenerateResourceOutput:
        """Apply the single post-revision deterministic contraction pass."""
        if request.requirements.revision_plan is None:
            raise GenerationError("revision_plan_required")
        return self._execute(
            request,
            {candidate.resource_type: candidate for candidate in candidates},
            removable_claims_by_type,
            deterministic_only=True,
        )

    def _execute(
        self,
        request: GenerateResourceInput,
        candidates_by_type: dict[ResourceType, GeneratedResourceArtifact],
        audited_claims_by_type: dict[ResourceType, dict[str, list[str]]],
        *,
        deterministic_only: bool = False,
    ) -> GenerateResourceOutput:
        if not isinstance(request, GenerateResourceInput):
            self._logger.warning("generation_rejected error_code=invalid_generate_input_type")
            raise GenerationError("invalid_generate_input_type")

        try:
            validated = GenerateResourceInput.model_validate(request.model_dump(mode="python"))
            if self._renderer is None:
                raise GenerationError("generation_renderer_not_configured")
            evidenced_ids = {chunk.knowledge_id for chunk in validated.retrieved_chunks}
            missing_evidence = sorted(
                set(validated.requirements.required_knowledge_ids) - evidenced_ids
            )
            if missing_evidence:
                self._logger.warning(
                    "generation_missing_target_evidence task_id=%s knowledge_ids=%s",
                    validated.task_id,
                    missing_evidence,
                )
            sources_by_id = {
                chunk.source.source_ref_id: chunk.source for chunk in validated.retrieved_chunks
            }

            def generate_one(resource_type: ResourceType) -> GeneratedResourceArtifact:
                target_ids = set(validated.requirements.resource_knowledge_targets[resource_type])
                question_source_ids = (
                    {
                        str(source_ref_id)
                        for question in validated.reference_questions
                        for source_ref_id in question.answer_key.get("source_ref_ids") or []
                    }
                    if resource_type is ResourceType.GRADED_QUIZ
                    else set()
                )
                allowed_sources = [
                    chunk.source
                    for chunk in validated.retrieved_chunks
                    if chunk.source.source_ref_id in validated.requirements.source_whitelist
                    and (
                        chunk.knowledge_id in target_ids
                        or chunk.source.source_ref_id in question_source_ids
                    )
                ]
                if not allowed_sources:
                    allowed_sources = [
                        sources_by_id[source_id]
                        for source_id in validated.requirements.source_whitelist
                    ]
                previous_candidate = candidates_by_type.get(resource_type)
                if resource_type is ResourceType.GRADED_QUIZ:
                    excluded_question_ids: set[str] = set()
                    if previous_candidate is not None:
                        previous_content = previous_candidate.structured_content
                        if not isinstance(previous_content, GradedQuizContent):
                            raise GenerationError("revision_candidate_type_mismatch")
                        rejected_indexes = quiz_revision_question_indexes(
                            validated.requirements.revision_plan
                        )
                        if not rejected_indexes:
                            # A formal-bank quiz cannot be repaired with free-form text.
                            # If review did not identify a position, force a genuinely new
                            # paper or fail clearly when the bank has no alternative.
                            rejected_indexes = list(range(len(previous_content.questions)))
                        excluded_question_ids = {
                            previous_content.questions[index].question_id
                            for index in rejected_indexes
                            if 0 <= index < len(previous_content.questions)
                        }
                    try:
                        response = GeneratedContentResponse(
                            structured_content=build_graded_quiz_from_question_bank(
                                validated,
                                allowed_sources,
                                excluded_question_ids=excluded_question_ids,
                            ),
                            difficulty=validated.requirements.target_difficulty,
                        )
                    except QuestionBankError as exc:
                        raise GenerationError(str(exc)) from exc
                elif previous_candidate is None:
                    response = GeneratedContentResponse.model_validate(
                        self._generator.generate(validated, resource_type, allowed_sources)
                    )
                else:
                    candidate_response = GeneratedContentResponse(
                        structured_content=previous_candidate.structured_content,
                        difficulty=previous_candidate.difficulty,
                    )
                    revise = getattr(self._generator, "revise", None)
                    try:
                        proposed = (
                            RevisionPatchResponse()
                            if deterministic_only
                            else (
                            revise(
                                validated,
                                resource_type,
                                allowed_sources,
                                candidate_response,
                            )
                            if callable(revise)
                            else RevisionPatchResponse()
                            )
                        )
                    except ModelResponseError as exc:
                        # The previous candidate already passed the frozen contract.  A
                        # malformed model response must not destroy that valid recovery
                        # point.  Record only sanitized validation metadata, then let the
                        # deterministic merge remove the audited claims below.  The result
                        # still goes through source, coverage and dual-model quality gates.
                        record_model_call(
                            exc.metadata,
                            role="generation_model",
                            resource_type=resource_type.value,
                            correction_attempt=(
                                validated.requirements.revision_plan.revision_count
                            ),
                            correction_kind="field_revision_structure_fallback",
                        )
                        self._logger.warning(
                            "generation_revision_structure_fallback task_id=%s "
                            "resource_type=%s validation_fields=%s",
                            validated.task_id,
                            resource_type.value,
                            [
                                str(field)[:160]
                                for field in exc.metadata.get("validation_fields", [])
                            ][:20],
                        )
                        proposed = RevisionPatchResponse()
                    field_paths = validated.requirements.revision_plan.field_paths_by_resource.get(
                        resource_type, []
                    )
                    if isinstance(proposed, RevisionPatchResponse):
                        proposed, rejected_paths = _sanitize_revision_patches(
                            candidate_response,
                            proposed,
                            field_paths,
                        )
                        if rejected_paths:
                            self._logger.warning(
                                "generation_revision_patch_filtered task_id=%s "
                                "resource_type=%s rejected_paths=%s accepted_count=%s",
                                validated.task_id,
                                resource_type.value,
                                rejected_paths[:20],
                                len(proposed.patches),
                            )
                        try:
                            response = _apply_revision_patches(
                                candidate_response,
                                proposed,
                                field_paths,
                                audited_claims_by_type.get(resource_type, {}),
                            )
                        except GenerationError as exc:
                            if str(exc) != "patch_validation_failed":
                                raise
                            # Reject the invalid model patch, then recover from
                            # the valid candidate by removing only audited
                            # unsupported claims. This is still revalidated by
                            # structure, source, coverage and both review models.
                            self._logger.warning(
                                "generation_revision_patch_fallback task_id=%s "
                                "resource_type=%s rejected_paths=%s",
                                validated.task_id,
                                resource_type.value,
                                [patch.path[:160] for patch in proposed.patches[:20]],
                            )
                            response = _apply_revision_patches(
                                candidate_response,
                                RevisionPatchResponse(),
                                field_paths,
                                audited_claims_by_type.get(resource_type, {}),
                            )
                    else:
                        # Compatibility for deterministic test doubles; the live
                        # The live gateway always uses the typed patch response.
                        response = _merge_revision_candidate(
                            candidate_response,
                            GeneratedContentResponse.model_validate(proposed),
                            field_paths,
                            audited_claims_by_type.get(resource_type, {}),
                        )
                    before_fingerprints = _revision_field_fingerprints(
                        candidate_response.structured_content,
                        validated.requirements.revision_plan.field_paths_by_resource.get(
                            resource_type, []
                        ),
                    )
                    after_fingerprints = _revision_field_fingerprints(
                        response.structured_content,
                        validated.requirements.revision_plan.field_paths_by_resource.get(
                            resource_type, []
                        ),
                    )
                    changed_paths = sorted(
                        path
                        for path, fingerprint in after_fingerprints.items()
                        if before_fingerprints.get(path) != fingerprint
                    )
                    self._logger.info(
                        "generation_revision_merge task_id=%s resource_type=%s "
                        "target_path_count=%s changed_paths=%s unchanged_paths=%s",
                        validated.task_id,
                        resource_type.value,
                        len(after_fingerprints),
                        changed_paths,
                        sorted(set(after_fingerprints) - set(changed_paths)),
                    )
                whitelist = {source.source_ref_id for source in allowed_sources}
                for attempt in range(MAX_SOURCE_REPAIR_ATTEMPTS + 1):
                    if response.structured_content.resource_type != resource_type.value:
                        raise GenerationError("generated_resource_type_mismatch")
                    violations = _source_violations(response.structured_content, whitelist)
                    if not violations:
                        break
                    if previous_candidate is not None:
                        raise GenerationError("revision_candidate_source_missing")
                    if attempt == MAX_SOURCE_REPAIR_ATTEMPTS:
                        self._logger.warning(
                            "generation_source_repair_exhausted task_id=%s resource_type=%s "
                            "attempts=%s whitelist_count=%s violation_paths=%s invalid_source_ids=%s",
                            validated.task_id,
                            resource_type.value,
                            MAX_SOURCE_REPAIR_ATTEMPTS,
                            len(whitelist),
                            [item["path"] for item in violations][:20],
                            sorted({item["source_ref_id"] for item in violations})[:20],
                        )
                        raise GenerationError("generated_source_outside_whitelist_after_repair")
                    repair = getattr(self._generator, "repair", None)
                    if callable(repair):
                        response = GeneratedContentResponse.model_validate(
                            repair(
                                validated,
                                resource_type,
                                allowed_sources,
                                response,
                                violations,
                                attempt + 1,
                            )
                        )
                    else:
                        response = GeneratedContentResponse.model_validate(
                            self._generator.generate(validated, resource_type, allowed_sources)
                        )

                if (
                    previous_candidate is not None
                    and resource_type is not ResourceType.GRADED_QUIZ
                ):
                    response = _strip_audited_claims_after_repairs(
                        response,
                        resource_type,
                        audited_claims_by_type.get(resource_type, {}),
                    )
                response = response.model_copy(
                    update={
                        "structured_content": normalize_generated_content(
                            response.structured_content
                        )
                    }
                )
                if _source_violations(response.structured_content, whitelist):
                    raise GenerationError("generated_source_outside_whitelist_after_repair")

                if resource_type == ResourceType.GRADED_QUIZ:
                    blueprint = _quiz_blueprint(
                        validated,
                        allowed_sources,
                        excluded_question_ids=excluded_question_ids,
                    )
                    quiz_violations = _quiz_blueprint_violations(
                        response.structured_content,
                        blueprint,
                        validated,
                    )
                    if quiz_violations:
                        self._logger.warning(
                            "graded_quiz_question_bank_invalid task_id=%s "
                            "question_ids=%s fields=%s",
                            validated.task_id,
                            [item["question_id"] for item in quiz_violations],
                            [item["field"] for item in quiz_violations],
                        )
                        raise GenerationError("graded_quiz_question_bank_invalid")
                    violations = _source_violations(response.structured_content, whitelist)
                    if violations:
                        raise GenerationError("generated_source_outside_whitelist_after_repair")

                covered_final = _covered_knowledge_ids(
                    response.structured_content, validated, resource_type
                )
                missing_coverage = sorted(target_ids - covered_final)
                if missing_coverage:
                    self._logger.warning(
                        "generated_coverage_incomplete task_id=%s resource_type=%s "
                        "knowledge_ids=%s",
                        validated.task_id,
                        resource_type.value,
                        missing_coverage,
                    )

                used_source_ids = structured_source_ref_ids(response.structured_content)
                source_refs = [
                    sources_by_id[source_id]
                    for source_id in validated.requirements.source_whitelist
                    if source_id in used_source_ids
                ]
                return GeneratedResourceArtifact(
                    resource_type=resource_type,
                    structured_content=response.structured_content,
                    content_md=self._renderer(response.structured_content, source_refs),
                    difficulty=response.difficulty,
                    source_refs=source_refs,
                    knowledge_coverage={
                        knowledge_id: sorted(
                            source_id
                            for source_id in used_source_ids
                            if sources_by_id[source_id].knowledge_id == knowledge_id
                        )
                        for knowledge_id in validated.requirements.resource_knowledge_targets[
                            resource_type
                        ]
                        if any(
                            sources_by_id[source_id].knowledge_id == knowledge_id
                            for source_id in used_source_ids
                        )
                    },
                    review_claims=build_review_claims(
                        resource_type, response.structured_content
                    ),
                )

            resource_types = validated.requirements.resource_types
            # ContextVars do not automatically cross executor threads.  Copy the
            # task-scoped collector so every resource generation is recorded.
            contexts = [copy_context() for _ in resource_types]
            with ThreadPoolExecutor(
                max_workers=min(len(resource_types), settings.generation_model_concurrency)
            ) as executor:
                futures = [
                    executor.submit(context.run, generate_one, resource_type)
                    for context, resource_type in zip(contexts, resource_types, strict=True)
                ]
                resources_by_type: dict[ResourceType, GeneratedResourceArtifact] = {}
                failures: dict[ResourceType, Exception] = {}
                for resource_type, future in zip(resource_types, futures, strict=True):
                    try:
                        resources_by_type[resource_type] = future.result()
                    except Exception as exc:  # settled and retried below per resource
                        failures[resource_type] = exc

            for resource_type in list(failures):
                try:
                    resources_by_type[resource_type] = copy_context().run(
                        generate_one, resource_type
                    )
                    del failures[resource_type]
                except Exception as exc:
                    failures[resource_type] = exc
            if failures:
                failed_types = sorted(item.value for item in failures)
                self._logger.warning(
                    "generation_resource_failed task_id=%s resource_types=%s error_codes=%s",
                    validated.task_id,
                    failed_types,
                    [
                        getattr(failures[item], "code", type(failures[item]).__name__)
                        for item in failures
                    ],
                )
                first_type = next(iter(failures))
                first_error = failures[first_type]
                if isinstance(
                    first_error,
                    (GenerationError, ModelResponseError, ModelCallError, ValidationError),
                ):
                    raise first_error
                raise GenerationError(
                    "generation_resource_failed:" + ",".join(failed_types)
                ) from first_error
            resources = [resources_by_type[item] for item in resource_types]
            output = GenerateResourceOutput(task_id=validated.task_id, resources=resources)
        except GenerationError:
            self._log_failure(request, "generation_policy_rejected")
            raise
        except ModelResponseError as exc:
            record_model_call(
                exc.metadata,
                role="generation_model",
                resource_type=getattr(exc, "resource_type", "unknown"),
                correction_kind=getattr(exc, "correction_kind", None),
            )
            self._log_failure(request, "generated_structured_output_invalid")
            raise GenerationError("generated_structured_output_invalid") from exc
        except ModelCallError as exc:
            self._log_failure(request, "model_call_failed")
            raise GenerationError("model_call_failed") from exc
        except (KeyError, ValidationError) as exc:
            revision = getattr(request, "requirements", None) and request.requirements.revision_plan
            error_code = (
                "patch_validation_failed"
                if revision
                else "generated_structure_validation_failed"
            )
            validation_fields = (
                [".".join(str(part) for part in item["loc"]) for item in exc.errors()]
                if isinstance(exc, ValidationError)
                else ["mapping_key"]
            )
            self._logger.warning(
                "generation_validation_failed task_id=%s error_code=%s validation_fields=%s",
                getattr(request, "task_id", "unknown"),
                error_code,
                validation_fields[:20],
            )
            self._log_failure(request, error_code)
            raise GenerationError(error_code, field_paths=validation_fields) from exc
        except Exception as exc:
            self._log_failure(request, "generation_execution_failed")
            raise GenerationError("generation_execution_failed") from exc

        self._logger.info(
            "generation_completed task_id=%s resource_types=%s source_count=%s",
            output.task_id,
            [resource.resource_type for resource in output.resources],
            len(validated.requirements.source_whitelist),
        )
        return output

    def _log_failure(self, request: GenerateResourceInput, error_code: str) -> None:
        self._logger.warning(
            "generation_failed task_id=%s error_code=%s",
            getattr(request, "task_id", "unknown"),
            error_code,
        )


def _generation_payload(
    request: GenerateResourceInput,
    resource_type: ResourceType,
    allowed_sources: list[SourceRef],
    *,
    candidate: GeneratedContentResponse | None = None,
    violations: list[dict[str, str]] | None = None,
    correction_attempt: int = 0,
    missing_knowledge_ids: list[str] | None = None,
    preserve_knowledge_ids: list[str] | None = None,
    response_model: type[BaseModel] | None = None,
    quiz_violations: list[dict[str, object]] | None = None,
    evidence_capabilities_by_knowledge: dict[str, list[str]] | None = None,
) -> dict[str, object]:
    chunks_by_source = {chunk.source.source_ref_id: chunk for chunk in request.retrieved_chunks}
    allowed_source_ref_ids = [source.source_ref_id for source in allowed_sources]
    target_ids = request.requirements.resource_knowledge_targets[resource_type]
    payload: dict[str, object] = {
        "task_id": request.task_id,
        "resource_type": resource_type.value,
        "profile_brief": {
            "profile_type": request.profile.profile_type.value,
            "ability_scores": request.profile.ability_scores.model_dump(mode="json"),
            "relevant_weak_knowledge": [
                item.model_dump(mode="json")
                for item in request.profile.weak_knowledge
                if item.knowledge_id in target_ids
            ],
        },
        "requirements": {
            "target_difficulty": request.requirements.target_difficulty,
            "strategy": request.requirements.strategy.value,
            "adaptation_notes": request.requirements.adaptation_notes,
        },
        "retrieved_knowledge": [
            chunks_by_source[source.source_ref_id].model_dump(mode="json")
            | {"content": bounded_text(chunks_by_source[source.source_ref_id].content)}
            for source in allowed_sources
        ],
        "evidence_capabilities": evidence_capability_payload(
            [chunks_by_source[source.source_ref_id] for source in allowed_sources],
            request.context.domain_code,
            evidence_capabilities_by_knowledge,
        ),
        "allowed_source_ref_ids": allowed_source_ref_ids,
        "resource_target_knowledge_ids": target_ids,
        "current_path_node": (
            request.current_path_node.model_dump(mode="json")
            if request.current_path_node is not None
            else None
        ),
        "missing_knowledge_ids": missing_knowledge_ids
        if missing_knowledge_ids is not None
        else (
            request.requirements.revision_plan.missing_knowledge_ids_by_resource.get(
                resource_type, []
            )
            if request.requirements.revision_plan
            else []
        ),
        "preserve_knowledge_ids": preserve_knowledge_ids
        if preserve_knowledge_ids is not None
        else (
            request.requirements.revision_plan.preserve_knowledge_ids_by_resource.get(
                resource_type, []
            )
            if request.requirements.revision_plan
            else []
        ),
        "revision_claim_ids": (
            request.requirements.revision_plan.claim_ids_by_resource.get(resource_type, [])
            if request.requirements.revision_plan
            else []
        ),
        "revision_field_paths": (
            request.requirements.revision_plan.field_paths_by_resource.get(resource_type, [])
            if request.requirements.revision_plan
            else []
        ),
        "coverage_rules": [
            "只需覆盖 resource_target_knowledge_ids，不要求单份资源重复整个学习包",
            "每个目标知识点必须出现在实质内容中并引用其对应知识库来源",
            "修订时保留已覆盖知识点，优先补齐 revision_plan 指定的缺失知识点",
            "修订时只改动 revision_field_paths 指向的事实字段和缺失知识点，不重写已通过资源",
        ],
        "source_reference_rules": [
            "source_ref_ids 只能逐字复制 allowed_source_ref_ids 中的值",
            "禁止使用 knowledge_id、source_title、source_url 或自行构造的 ID",
            "没有证据支持的内容必须删除或重写",
            "不得根据模型常识补充证据未明确出现的版本号、能力边界、工具替代关系或强因果结论",
            "Structured Outputs、SQLAlchemy、Alembic 等术语只能表达 retrieved_knowledge 明确支持的范围",
            "环境要求、预期结果、排错结论、答案和解析同样属于事实性内容，必须有证据支持",
            "summary 只能总结已讲授的知识结论，不得声称资料权威性、引用完整性或未引入外部推断",
            "命令、配置、预期结果和排错结论只能在绑定证据正文直接支持时生成",
            "必须遵守 evidence_capabilities：缺少 command/code_example 时 code_or_command 必须为 null",
            "缺少 expected_result 时不得声称固定输出；缺少 error_handling 时 troubleshooting 必须为 null",
        ],
        "personalization_rules": [
            "允许按画像调整顺序、难度、解释粒度、示例组织和练习形式",
            "个性化只改变教学组织，不得创造 retrieved_knowledge 之外的技术事实",
            "生成前在内部建立字段—事实—source_ref_id 映射，输出中无需展示该内部映射",
            "纯教学动作不需要伪装成技术结论；混合句中的技术部分仍必须绑定直接证据",
        ],
        "output_schema": _source_constrained_schema(
            response_model or _response_model_for(resource_type), allowed_source_ref_ids
        ),
    }
    if resource_type == ResourceType.GRADED_QUIZ:
        payload["quiz_blueprint"] = _quiz_blueprint(request, allowed_sources)
        payload["quiz_fact_rules"] = [
            "每道题的题干事实前提、正确答案和解析必须分别由该题 source_ref_ids 的证据原文直接推出",
            "禁止把证据中分别出现的概念改写成共同、核心、保证、决定、导致等新关系",
            "单选和多选的 correct_answer 必须逐字复制一个或多个 options 文本",
            "短答题答案优先使用证据原文中的最小连续表述，不增加目的、效果或权威性说明",
            "不得在 prompt、correct_answer、explanation 中显示 source_ref_id、chunk ID 或内部知识 ID",
        ]
        payload["reference_questions"] = [
            item.model_dump(mode="json")
            for item in request.reference_questions
            if item.knowledge_id in target_ids
        ]
    if candidate is not None:
        payload["correction_attempt"] = correction_attempt
        payload["candidate"] = candidate.model_dump(mode="json")
        payload["source_violations"] = violations or []
    if quiz_violations is not None:
        payload["quiz_violations"] = quiz_violations
        payload["preserve_question_ids"] = [
            slot["question_id"]
            for slot in _quiz_blueprint(request, allowed_sources)
            if slot["question_id"] not in {item.get("question_id") for item in quiz_violations}
        ]
    if estimate_tokens(payload) > 12_000:
        raise GenerationError("generation_prompt_budget_exceeded")
    return payload


def _covered_knowledge_ids(
    content: StructuredResourceContent,
    request: GenerateResourceInput,
    resource_type: ResourceType,
) -> set[str]:
    used_source_ids = _substantive_source_ids(content)
    knowledge_by_source = {
        chunk.source.source_ref_id: chunk.knowledge_id for chunk in request.retrieved_chunks
    }
    targets = set(request.requirements.resource_knowledge_targets[resource_type])
    return {
        knowledge_by_source[source_id]
        for source_id in used_source_ids
        if source_id in knowledge_by_source and knowledge_by_source[source_id] in targets
    }


def _substantive_source_ids(content: StructuredResourceContent) -> set[str]:
    """Only count references attached to meaningful teaching or assessment text."""
    result: set[str] = set()

    def meaningful(*values: str | None) -> bool:
        normalized = " ".join(value.strip() for value in values if value).strip()
        # Concise seed knowledge such as “RAG 资源必须保留可追溯来源” is still
        # substantive. Reject empty/title-like placeholders without imposing an
        # arbitrary paragraph-length requirement on valid atomic knowledge.
        compact = re.sub(r"\s+", "", normalized)
        placeholders = {"待补充", "暂无", "无", "todo", "tbd", "示例内容", "模板内容"}
        return len(compact) >= 8 and compact.lower() not in placeholders

    if isinstance(content, LectureContent):
        for block in content.core_concepts:
            if meaningful(block.explanation, block.example):
                result.update(block.source_ref_ids)
        for block in content.misconceptions:
            if meaningful(block.misconception, block.correction):
                result.update(block.source_ref_ids)
        return result
    if isinstance(content, PracticeGuideContent):
        for step in content.steps:
            if meaningful(
                step.instruction,
                step.code_or_command,
                step.expected_result,
                step.troubleshooting,
            ):
                result.update(step.source_ref_ids)
        return result
    for question in content.questions:
        if meaningful(question.prompt, question.correct_answer, question.explanation):
            result.update(question.source_ref_ids)
    return result


_EDITABLE_REVISION_PATHS = {
    ResourceType.LECTURE: (
        re.compile(r"^summary$"),
        re.compile(r"^core_concepts\[\d+\]\.(?:explanation|example)$"),
        re.compile(r"^misconceptions\[\d+\]\.(?:misconception|correction)$"),
    ),
    ResourceType.PRACTICE_GUIDE: (
        re.compile(r"^environment_requirements\[\d+\]$"),
        re.compile(r"^steps\[\d+\]\.(?:instruction|code_or_command|expected_result|troubleshooting)$"),
        re.compile(r"^acceptance_criteria\[\d+\]$"),
    ),
    ResourceType.GRADED_QUIZ: (
        re.compile(r"^questions\[\d+\]\.(?:prompt|correct_answer|explanation)$"),
    ),
}


def _normalize_revision_path(path: str, resource_type: ResourceType) -> str | None:
    candidate = path.strip()
    patterns = _EDITABLE_REVISION_PATHS[resource_type]
    while candidate:
        if any(pattern.fullmatch(candidate) for pattern in patterns):
            return candidate
        shortened = re.sub(r"\[\d+\]$", "", candidate)
        if shortened == candidate:
            return None
        candidate = shortened
    return None


def _path_tokens(path: str) -> list[str | int]:
    tokens: list[str | int] = []
    for name, index in re.findall(r"([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]", path):
        tokens.append(name if name else int(index))
    return tokens


def _read_path(payload: object, tokens: list[str | int]) -> object:
    current = payload
    for token in tokens:
        current = current[token]  # type: ignore[index]
    return current


def _write_path(payload: object, tokens: list[str | int], value: object) -> None:
    current = payload
    for token in tokens[:-1]:
        current = current[token]  # type: ignore[index]
    current[tokens[-1]] = value  # type: ignore[index]


def _revision_patch_fixture(
    candidate: GeneratedContentResponse, field_paths: list[str]
) -> RevisionPatchResponse:
    resource_type = ResourceType(candidate.structured_content.resource_type)
    payload = candidate.structured_content.model_dump(mode="python")
    patches: list[RevisionFieldPatch] = []
    for requested in field_paths:
        path = _normalize_revision_path(requested, resource_type)
        if path is None or any(item.path == path for item in patches):
            continue
        try:
            value = _read_path(payload, _path_tokens(path))
        except (IndexError, KeyError, TypeError):
            continue
        if isinstance(value, str) or value is None:
            patches.append(RevisionFieldPatch(path=path, value=value))
    return RevisionPatchResponse(patches=patches)


def _apply_revision_patches(
    original: GeneratedContentResponse,
    proposed: RevisionPatchResponse,
    field_paths: list[str],
    audited_claims: dict[str, list[str]] | None = None,
) -> GeneratedContentResponse:
    """Apply typed field patches without allowing structural resource rewrites."""
    resource_type = ResourceType(original.structured_content.resource_type)
    allowed = {
        normalized
        for path in field_paths
        if (normalized := _normalize_revision_path(path, resource_type)) is not None
    }
    payload = original.structured_content.model_dump(mode="python")
    seen: set[str] = set()
    for patch in proposed.patches:
        normalized = _normalize_revision_path(patch.path, resource_type)
        if normalized is None or normalized not in allowed or normalized in seen:
            raise GenerationError("patch_validation_failed")
        seen.add(normalized)
        tokens = _path_tokens(normalized)
        try:
            old_value = _read_path(payload, tokens)
        except (IndexError, KeyError, TypeError) as exc:
            raise GenerationError("patch_validation_failed") from exc
        if old_value is not None and not isinstance(old_value, str):
            raise GenerationError("patch_validation_failed")
        if old_value is not None and patch.value is None and not normalized.endswith(
            (".code_or_command", ".troubleshooting")
        ):
            raise GenerationError("patch_validation_failed")
        if isinstance(old_value, str) and isinstance(patch.value, str):
            if _claim_unit_count(patch.value) > max(1, _claim_unit_count(old_value)):
                raise GenerationError("patch_validation_failed")
        _write_path(payload, tokens, patch.value)
    _remove_residual_audited_claims(payload, resource_type, audited_claims or {})
    try:
        content = type(original.structured_content).model_validate(payload)
    except ValidationError as exc:
        raise GenerationError("patch_validation_failed") from exc
    return GeneratedContentResponse(
        structured_content=content,
        difficulty=original.difficulty,
    )


def _sanitize_revision_patches(
    original: GeneratedContentResponse,
    proposed: RevisionPatchResponse,
    field_paths: list[str],
) -> tuple[RevisionPatchResponse, list[str]]:
    """Keep independent valid patches and bound each replacement's claim surface."""
    resource_type = ResourceType(original.structured_content.resource_type)
    allowed = {
        normalized
        for path in field_paths
        if (normalized := _normalize_revision_path(path, resource_type)) is not None
    }
    payload = original.structured_content.model_dump(mode="python")
    accepted: list[RevisionFieldPatch] = []
    rejected: list[str] = []
    seen: set[str] = set()
    for patch in proposed.patches:
        normalized = _normalize_revision_path(patch.path, resource_type)
        if normalized is None or normalized not in allowed or normalized in seen:
            rejected.append(patch.path[:160])
            continue
        try:
            old_value = _read_path(payload, _path_tokens(normalized))
        except (IndexError, KeyError, TypeError):
            rejected.append(patch.path[:160])
            continue
        if old_value is not None and not isinstance(old_value, str):
            rejected.append(patch.path[:160])
            continue
        if old_value is not None and patch.value is None and not normalized.endswith(
            (".code_or_command", ".troubleshooting")
        ):
            rejected.append(patch.path[:160])
            continue
        value = patch.value
        if isinstance(old_value, str) and isinstance(value, str):
            value = _truncate_claim_units(value, max(1, _claim_unit_count(old_value)))
            if not value.strip():
                rejected.append(patch.path[:160])
                continue
        accepted.append(RevisionFieldPatch(path=normalized, value=value))
        seen.add(normalized)
    return RevisionPatchResponse(patches=accepted), rejected


def _claim_unit_count(value: object) -> int:
    if not isinstance(value, str):
        return 0
    return len([item for item in re.split(r"[。！？!?；;\n]+", value) if item.strip()])


def _truncate_claim_units(value: str, maximum: int) -> str:
    units = [
        item.strip()
        for item in re.findall(r"[^。！？!?；;\n]+[。！？!?；;\n]*", value)
        if item.strip()
    ]
    return "".join(units[:maximum]).strip() if units else value.strip()


def _merge_revision_candidate(
    original: GeneratedContentResponse,
    proposed: GeneratedContentResponse,
    field_paths: list[str],
    audited_claims: dict[str, list[str]] | None = None,
) -> GeneratedContentResponse:
    """Apply only audited fields and reject edits that expand factual surface."""
    resource_type = ResourceType(original.structured_content.resource_type)
    if proposed.structured_content.resource_type != resource_type.value:
        return original
    original_payload = original.structured_content.model_dump(mode="python")
    proposed_payload = proposed.structured_content.model_dump(mode="python")
    merged_payload = original.structured_content.model_dump(mode="python")
    normalized_paths = list(
        dict.fromkeys(
            normalized
            for path in field_paths
            if (normalized := _normalize_revision_path(path, resource_type)) is not None
        )
    )
    for path in normalized_paths:
        tokens = _path_tokens(path)
        try:
            old_value = _read_path(original_payload, tokens)
            new_value = _read_path(proposed_payload, tokens)
        except (IndexError, KeyError, TypeError):
            continue
        if type(new_value) is not type(old_value):
            continue
        if isinstance(old_value, str) and _claim_unit_count(new_value) > max(
            1, _claim_unit_count(old_value)
        ):
            continue
        _write_path(merged_payload, tokens, new_value)
    _remove_residual_audited_claims(
        merged_payload,
        resource_type,
        audited_claims or {},
    )
    content_type = type(original.structured_content)
    merged_content = content_type.model_validate(merged_payload)
    return GeneratedContentResponse(
        structured_content=merged_content,
        difficulty=original.difficulty,
    )


def _remove_residual_audited_claims(
    payload: dict[str, object],
    resource_type: ResourceType,
    audited_claims: dict[str, list[str]],
) -> None:
    """Remove rejected atomic prose that a model proposal left unchanged."""
    claims_by_parent: dict[str, list[str]] = {}
    for field_path, claims in audited_claims.items():
        parent = _normalize_revision_path(field_path, resource_type)
        if parent is not None:
            claims_by_parent.setdefault(parent, []).extend(claims)

    for parent, claims in claims_by_parent.items():
        tokens = _path_tokens(parent)
        try:
            value = _read_path(payload, tokens)
        except (IndexError, KeyError, TypeError):
            continue
        if not isinstance(value, str):
            continue
        cleaned = value
        for claim in dict.fromkeys(claims):
            normalized = _audited_claim_body(parent, claim).strip().strip("。！？!?；;，,")
            if normalized and normalized in cleaned:
                cleaned = cleaned.replace(normalized, "", 1)
        cleaned = re.sub(r"^[\s。！？!?；;，,]+|[\s；;，,]+$", "", cleaned)
        cleaned = re.sub(r"([。！？!?；;，,])\s*[。！？!?；;，,]+", r"\1", cleaned)
        if cleaned != value:
            replacement: str | None = cleaned or _revision_fallback_text(parent)
            if not cleaned and parent.endswith((".code_or_command", ".troubleshooting")):
                replacement = None
            _write_path(payload, tokens, replacement)


def _strip_audited_claims_after_repairs(
    response: GeneratedContentResponse,
    resource_type: ResourceType,
    audited_claims: dict[str, list[str]],
) -> GeneratedContentResponse:
    """Prevent downstream full-candidate repairs from restoring rejected prose."""
    if not audited_claims:
        return response
    payload = response.structured_content.model_dump(mode="python")
    _remove_residual_audited_claims(payload, resource_type, audited_claims)
    try:
        content = type(response.structured_content).model_validate(payload)
    except ValidationError as exc:
        raise GenerationError("revision_post_repair_validation_failed") from exc
    return response.model_copy(update={"structured_content": content})


def _audited_claim_body(path: str, claim: str) -> str:
    markers = {
        ".code_or_command": "以下代码或命令应能完成该步骤：\n",
        ".prompt": "请判断该题题干中的事实前提是否准确：\n",
        ".correct_answer": "请判断该题正确答案是否准确：\n",
        ".explanation": "请判断该题解析是否准确：\n",
    }
    for suffix, marker in markers.items():
        if path.endswith(suffix) and marker in claim:
            return claim.split(marker, 1)[1]
    return claim


def _revision_fallback_text(path: str) -> str:
    """Return non-factual prose when an audited field contains only a rejected claim."""
    if path.startswith("environment_requirements["):
        return "练习前请确认所需材料与受控环境已经准备妥当。"
    if path.startswith("acceptance_criteria["):
        return "完成练习后，提交学习记录并标注核对依据。"
    if path.endswith(".instruction"):
        return "整理本步骤的学习要点，并记录学习结论。"
    if path.endswith(".expected_result"):
        return "形成与本步骤相关的学习检查表，列出关键观察项和核对结论。"
    if path.endswith(".troubleshooting"):
        return "记录问题现象，并依据引用材料逐项核对。"
    if path.endswith(".code_or_command"):
        return "请依据引用材料完成对应练习。"
    if path == "summary":
        return "回顾本讲义涉及的核心知识并整理学习记录。"
    if path.startswith("core_concepts[") or path.startswith("misconceptions["):
        return "阅读对应引用材料并整理其明确说明的知识要点。"
    if path.startswith("questions["):
        return "请根据引用材料完成该题并核对答案。"
    return "阅读引用材料并完成对应学习记录。"


def _revision_field_fingerprints(
    content: StructuredResourceContent, field_paths: list[str]
) -> dict[str, str]:
    """Hash normalized audited fields without logging their full text."""
    resource_type = ResourceType(content.resource_type)
    payload = content.model_dump(mode="python")
    result: dict[str, str] = {}
    for requested_path in field_paths:
        path = _normalize_revision_path(requested_path, resource_type)
        if path is None or path in result:
            continue
        try:
            value = _read_path(payload, _path_tokens(path))
        except (IndexError, KeyError, TypeError):
            continue
        normalized = re.sub(r"\s+", " ", str(value)).strip()
        result[path] = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return result


_NON_PROSE_POLICY_FIELDS = {
    "source_ref_ids",
    "reference_question_ids",
    "knowledge_id",
    "question_type",
    "level",
}


def _iter_policy_text_fields(value: object, path: str = "") -> list[tuple[str, str]]:
    """Enumerate auditable prose without resource-type-specific omissions."""
    if isinstance(value, BaseModel):
        return _iter_policy_text_fields(value.model_dump(mode="python"), path)
    if isinstance(value, dict):
        fields: list[tuple[str, str]] = []
        for key, nested in value.items():
            if key in _NON_PROSE_POLICY_FIELDS:
                continue
            child = f"{path}.{key}" if path else str(key)
            fields.extend(_iter_policy_text_fields(nested, child))
        return fields
    if isinstance(value, list):
        fields = []
        for index, nested in enumerate(value):
            fields.extend(_iter_policy_text_fields(nested, f"{path}[{index}]"))
        return fields
    if isinstance(value, str) and value.strip():
        return [(path, value)]
    return []


def _content_policy_violations(
    content: StructuredResourceContent,
) -> list[dict[str, str]]:
    """Run the single deterministic claim policy before semantic review."""
    values = _iter_policy_text_fields(content)
    violations: list[dict[str, str]] = []
    for path, value in values:
        _cleaned, codes = sanitize_deterministic_text(path, value)
        violations.extend({"path": path, "code": code} for code in codes)
        if (
            path.startswith("questions[")
            and path.endswith(".explanation")
            and _QUIZ_UNSUPPORTED_DISTRACTOR_RE.search(value)
        ):
            violations.append({"path": path, "code": "unsupported_distractor_rationale"})
    return violations


def normalize_generated_content(
    content: StructuredResourceContent,
) -> StructuredResourceContent:
    """Apply structural-safe cleanup without deciding whether facts are supported."""
    violations = _content_policy_violations(content)
    deterministic_paths = {
        item["path"]
        for item in violations
        if item["code"] in {"forbidden_meta_claim", "misplaced_field_content"}
    }
    normalized = _sanitize_deterministic_policy_claims(content, deterministic_paths)
    distractor_paths = {
        item["path"]
        for item in violations
        if item["code"] == "unsupported_distractor_rationale"
    }
    normalized = _sanitize_quiz_distractor_rationales(normalized, distractor_paths)
    if not isinstance(normalized, PracticeGuideContent):
        return normalized

    steps = []
    for index, step in enumerate(normalized.steps):
        updates: dict[str, str | None] = {}
        if not step.instruction.strip():
            updates["instruction"] = _revision_fallback_text(
                f"steps[{index}].instruction"
            )
        if not step.expected_result.strip():
            updates["expected_result"] = _revision_fallback_text(
                f"steps[{index}].expected_result"
            )
        for field in ("code_or_command", "troubleshooting"):
            value = getattr(step, field)
            if isinstance(value, str) and not value.strip():
                updates[field] = None
        command = updates.get("code_or_command", step.code_or_command)
        if isinstance(command, str):
            command = re.sub(
                r"(?<=[\w\"'<>])(?=git\s+(?:status|diff|add|commit|log|push|pull|"
                r"fetch|switch|checkout|merge|rebase|restore)\b)",
                "\n",
                command,
                flags=re.I,
            )
            updates["code_or_command"] = command
        steps.append(step.model_copy(update=updates) if updates else step)
    return normalized.model_copy(update={"steps": steps})


def _sanitize_quiz_distractor_rationales(
    content: StructuredResourceContent,
    paths: set[str],
) -> StructuredResourceContent:
    """Keep directly supported explanation clauses and drop absence-based distractor logic."""
    if not paths or not isinstance(content, GradedQuizContent):
        return content
    questions = []
    for index, question in enumerate(content.questions):
        path = f"questions[{index}].explanation"
        explanation = question.explanation
        if path in paths:
            clauses = re.findall(r"[^。！？!?；;]+[。！？!?；;]*", explanation)
            kept = [
                clause.strip()
                for clause in clauses
                if clause.strip() and not _QUIZ_UNSUPPORTED_DISTRACTOR_RE.search(clause)
            ]
            explanation = "".join(kept).strip() or (
                f"根据题干所列信息，正确答案为：{question.correct_answer}。"
            )
        questions.append(question.model_copy(update={"explanation": explanation}))
    return content.model_copy(update={"questions": questions})


def _sanitize_policy_text(path: str, value: str, fallback: str | None) -> str | None:
    """Remove deterministic policy violations without introducing new facts."""
    cleaned, _codes = sanitize_deterministic_text(path, value)
    if cleaned:
        return cleaned
    return fallback


def _sanitize_deterministic_policy_claims(
    content: StructuredResourceContent,
    paths: set[str],
) -> StructuredResourceContent:
    """Keep valid teaching text and fill required fields only when all text was removed."""
    if not paths:
        return content

    payload = content.model_dump(mode="python")

    def locate(path: str) -> tuple[object, str | int] | None:
        tokens: list[str | int] = []
        for name, index in re.findall(r"([^.\[\]]+)|\[(\d+)\]", path):
            tokens.append(int(index) if index else name)
        if not tokens:
            return None
        parent: object = payload
        for token in tokens[:-1]:
            try:
                parent = parent[token]  # type: ignore[index]
            except (KeyError, IndexError, TypeError):
                return None
        return parent, tokens[-1]

    def fallback(path: str) -> str | None:
        if path == "summary":
            return "请结合本讲义的核心概念，梳理关键要点并记录自己的理解。"
        if path.endswith(".example") or path.endswith(".code_or_command") or path.endswith(
            ".troubleshooting"
        ):
            return None
        if path.endswith(".title") or path == "title":
            return "学习内容"
        return _revision_fallback_text(path)

    for path in paths:
        located = locate(path)
        if located is None:
            continue
        parent, key = located
        try:
            value = parent[key]  # type: ignore[index]
        except (KeyError, IndexError, TypeError):
            continue
        if isinstance(value, str):
            cleaned = _sanitize_policy_text(path, value, None)
            parent[key] = cleaned if cleaned else fallback(path)  # type: ignore[index]
    return type(content).model_validate(payload)


def _source_constrained_schema(
    response_model: GenerationResponseModel, allowed_source_ref_ids: list[str]
) -> dict[str, Any]:
    schema = response_model.model_json_schema()

    def constrain(value: Any) -> None:
        if isinstance(value, dict):
            properties = value.get("properties")
            if isinstance(properties, dict) and "source_ref_ids" in properties:
                field = properties["source_ref_ids"]
                if isinstance(field, dict):
                    items = field.setdefault("items", {})
                    if isinstance(items, dict):
                        items["enum"] = allowed_source_ref_ids
            for nested in value.values():
                constrain(nested)
        elif isinstance(value, list):
            for nested in value:
                constrain(nested)

    constrain(schema)
    return schema


def _quiz_blueprint(
    request: GenerateResourceInput,
    allowed_sources: list[SourceRef],
    *,
    excluded_question_ids: set[str] | None = None,
) -> list[dict[str, object]]:
    """Fix quiz slots deterministically from the published formal question bank."""
    if request.reference_questions:
        try:
            content = build_graded_quiz_from_question_bank(
                request,
                allowed_sources,
                excluded_question_ids=excluded_question_ids or (),
            )
        except QuestionBankError:
            content = None
        if content is not None:
            return [
                {
                    "question_id": question.question_id,
                    "level": question.level.value,
                    "question_type": question.question_type.value,
                    "knowledge_id": question.knowledge_id,
                    "difficulty": question.difficulty,
                    "allowed_source_ref_ids": list(question.source_ref_ids),
                    "reference_question_ids": list(question.reference_question_ids),
                }
                for question in content.questions
            ]
    raise QuestionBankError("graded_quiz_question_bank_insufficient")


def _quiz_blueprint_violations(
    content: StructuredResourceContent,
    blueprint: list[dict[str, object]],
    request: GenerateResourceInput | None = None,
) -> list[dict[str, object]]:
    if not isinstance(content, GradedQuizContent):
        return [{"question_id": "<resource>", "field": "resource_type"}]
    questions_by_id = {question.question_id: question for question in content.questions}
    violations: list[dict[str, object]] = []
    if len(content.questions) != len(blueprint):
        violations.append({"question_id": "<package>", "field": "question_count"})
    for slot in blueprint:
        question_id = str(slot["question_id"])
        question = questions_by_id.get(question_id)
        if question is None:
            violations.append({"question_id": question_id, "field": "question_id"})
            continue
        expected = {
            "level": slot["level"],
            "question_type": slot["question_type"],
            "knowledge_id": slot["knowledge_id"],
            "difficulty": slot["difficulty"],
            "reference_question_ids": slot["reference_question_ids"],
        }
        actual = {
            "level": question.level.value,
            "question_type": question.question_type.value,
            "knowledge_id": question.knowledge_id,
            "difficulty": question.difficulty,
            "reference_question_ids": question.reference_question_ids,
        }
        for field, expected_value in expected.items():
            if actual[field] != expected_value:
                violations.append({"question_id": question_id, "field": field})
        allowed_sources = set(slot["allowed_source_ref_ids"])
        if not set(question.source_ref_ids).issubset(allowed_sources):
            violations.append({"question_id": question_id, "field": "source_ref_ids"})
        fallback = _revision_fallback_text(f"questions[{question_id}].prompt")
        if any(
            value.strip() == fallback
            for value in (question.prompt, question.correct_answer, question.explanation)
        ):
            violations.append({"question_id": question_id, "field": "assessment_content"})
        if question.question_type in {
            QuestionType.SINGLE_CHOICE,
            QuestionType.MULTIPLE_CHOICE,
        } and not _choice_answer_matches_options(question.correct_answer, question.options):
            violations.append({"question_id": question_id, "field": "correct_answer"})
        if request is not None and not _quiz_question_matches_target(question, slot, request):
            violations.append({"question_id": question_id, "field": "knowledge_alignment"})
    return violations


def _quiz_semantic_tokens(text: str) -> set[str]:
    lowered = text.lower()
    words = {word for word in re.findall(r"[a-z0-9_]+", lowered) if len(word) > 1}
    cjk = "".join(re.findall(r"[\u4e00-\u9fff]", lowered))
    words.update(cjk[index : index + 2] for index in range(max(0, len(cjk) - 1)))
    return words


def _quiz_question_matches_target(
    question: QuizQuestion,
    slot: dict[str, object],
    request: GenerateResourceInput,
) -> bool:
    """Validate a bank question's certified attribution deterministically.

    The formal-question certification already establishes that the stem, answer
    and rubric are supported by its primary knowledge item and declared real
    relations.  Re-comparing CJK token overlap at runtime is both lossy and
    incorrect for integrated questions: a question may legitimately use more
    terms from a related item than from its primary item.  Runtime only needs
    to confirm that the immutable blueprint attribution and certified evidence
    links have survived assembly.
    """
    if question.knowledge_id != str(slot["knowledge_id"]):
        return False
    if question.reference_question_ids != list(slot["reference_question_ids"]):
        return False
    allowed_source_ids = {str(value) for value in slot["allowed_source_ref_ids"]}
    question_source_ids = {str(value) for value in question.source_ref_ids}
    if not question_source_ids or not question_source_ids.issubset(allowed_source_ids):
        return False

    chunks_by_source = {chunk.source.source_ref_id: chunk for chunk in request.retrieved_chunks}
    return all(
        source_id in chunks_by_source
        and chunks_by_source[source_id].knowledge_id
        in {question.knowledge_id, *question.related_knowledge_ids}
        for source_id in question_source_ids
    )


def _candidate_evidence_body(value: str) -> str:
    """Remove Candidate embedding metadata before deriving fallback facts."""
    header_prefixes = ("知识点：", "分类：", "难度：", "标签：", "标题：")
    lines = value.splitlines()
    separator_index = next(
        (index for index, line in enumerate(lines) if not line.strip()),
        None,
    )
    if separator_index is None:
        return value
    header = [line.strip() for line in lines[:separator_index] if line.strip()]
    if not header or not all(line.startswith(header_prefixes) for line in header):
        return value
    body = "\n".join(lines[separator_index + 1 :]).strip()
    return body or value


def _choice_answer_matches_options(answer: str, options: list[str]) -> bool:
    """Reject unrelated choice answers while accepting text or A/B/C-style notation."""
    compact_answer = re.sub(r"\s+", "", answer).strip("。；;，,")
    if not compact_answer or not options:
        return False
    compact_options = [re.sub(r"\s+", "", option) for option in options]
    if any(option in compact_answer or compact_answer in option for option in compact_options):
        return True
    return bool(re.fullmatch(r"(?:[A-ZＡ-Ｚ](?:[、,，/\s]+|$))+", answer.strip(), re.I))


def _source_violations(
    content: StructuredResourceContent, whitelist: set[str]
) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []

    def inspect(value: Any, path: str = "structured_content") -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                next_path = f"{path}.{key}"
                if key == "source_ref_ids" and isinstance(nested, list):
                    if not nested:
                        violations.append({"path": next_path, "source_ref_id": "<missing>"})
                    for source_ref_id in nested:
                        if not isinstance(source_ref_id, str) or source_ref_id not in whitelist:
                            violations.append(
                                {"path": next_path, "source_ref_id": str(source_ref_id)}
                            )
                else:
                    inspect(nested, next_path)
        elif isinstance(value, list):
            for index, nested in enumerate(value):
                inspect(nested, f"{path}[{index}]")

    inspect(content.model_dump(mode="json"))
    if not structured_source_ref_ids(content):
        violations.append({"path": "structured_content", "source_ref_id": "<missing>"})
    return violations


def _fixture_response(
    request: GenerateResourceInput,
    resource_type: ResourceType,
    allowed_sources: list[SourceRef],
) -> GeneratedContentResponse:
    chunks_by_source = {chunk.source.source_ref_id: chunk for chunk in request.retrieved_chunks}
    first_source = allowed_sources[0]
    first_chunk = chunks_by_source[first_source.source_ref_id]
    source_ids = [source.source_ref_id for source in allowed_sources]
    audience = request.profile.profile_type.value
    title = f"{first_chunk.name}个性化学习资源"
    difficulty = request.requirements.target_difficulty

    if resource_type == ResourceType.LECTURE:
        content = LectureContent(
            title=title,
            target_audience=audience,
            learning_objectives=[f"理解{first_chunk.name}并能够追溯知识来源"],
            prerequisite_knowledge=[],
            core_concepts=[
                {
                    "title": first_chunk.name,
                    "explanation": first_chunk.content,
                    "example": None,
                    "source_ref_ids": source_ids,
                }
            ],
            misconceptions=[],
            summary=f"基于检索证据掌握{first_chunk.name}。",
        )
    elif resource_type == ResourceType.PRACTICE_GUIDE:
        content = PracticeGuideContent(
            title=title,
            target_audience=audience,
            learning_objectives=[f"完成{first_chunk.name}的最小可复现实操"],
            environment_requirements=["与引用材料相符的受控学习环境"],
            steps=[
                {
                    "order": 1,
                    "title": f"验证{first_chunk.name}",
                    "instruction": first_chunk.content,
                    "expected_result": "记录实际结果并与引用材料核对。",
                    "source_ref_ids": source_ids,
                }
            ],
            acceptance_criteria=["能够复现实操并指出所用知识来源。"],
        )
    else:
        questions = []
        chunks_by_knowledge = {chunk.knowledge_id: chunk for chunk in request.retrieved_chunks}
        for slot in _quiz_blueprint(request, allowed_sources):
            question_type = QuestionType(slot["question_type"])
            knowledge_id = str(slot["knowledge_id"])
            chunk = chunks_by_knowledge[knowledge_id]
            choice = question_type in {
                QuestionType.SINGLE_CHOICE,
                QuestionType.MULTIPLE_CHOICE,
            }
            questions.append(
                {
                    "question_id": slot["question_id"],
                    "level": slot["level"],
                    "question_type": slot["question_type"],
                    "prompt": f"说明{chunk.name}的关键点。",
                    "options": ["A. 正确做法", "B. 错误做法"] if choice else [],
                    "correct_answer": "A. 正确做法" if choice else chunk.content[:1000],
                    "explanation": "请根据该题绑定的知识材料核对答案依据。",
                    "knowledge_id": knowledge_id,
                    "difficulty": slot["difficulty"],
                    "source_ref_ids": slot["allowed_source_ref_ids"],
                    "reference_question_ids": slot["reference_question_ids"],
                }
            )
        content = GradedQuizContent(
            title=title,
            target_audience=audience,
            learning_objectives=[f"分层检验对{first_chunk.name}的掌握程度"],
            questions=questions,
        )

    return GeneratedContentResponse(structured_content=content, difficulty=difficulty)
