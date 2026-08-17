"""V3 content generation Agent with structured generation and deterministic rendering."""

from __future__ import annotations

import hashlib
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from collections.abc import Callable
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from app.agents.contracts import (
    GenerateResourceInput,
    GenerateResourceOutput,
    GeneratedResourceArtifact,
    GradedQuizContent,
    LectureContent,
    PracticeGuideContent,
    QuestionType,
    QuizLevel,
    ResourceType,
    SourceRef,
    StructuredResourceContent,
    structured_source_ref_ids,
)
from app.agents.observability import record_model_call
from app.agents.domain_evidence_policy import (
    EvidenceCapability,
    evidence_capability_payload,
    get_domain_evidence_policy,
)
from app.agents.prompt_budget import bounded_text, estimate_tokens
from app.core.config import settings
from app.services.llm_service import ModelResponseError, OpenAICompatibleGateway, gateway


GENERATION_AGENT_NAME = "content_generation_agent_v3"
SYSTEM_PROMPT = (
    "你是内容生成智能体。必须仅复述和组织输入 retrieved_knowledge 中明确出现的信息，"
    "不得调用检索、数据库或向量库，不得使用模型自身常识补全版本号、能力边界、工具关系、"
    "因果关系或最佳实践。证据未明确说明的事实必须删除或改写为不含额外结论的学习提示。"
    "所有事实性内容必须关联输入白名单中的 source_ref_ids。只返回结构化内容，不生成"
    "content_md，不负责审核或发布决策。summary 只能总结已讲授的知识结论，"
    "不得声称内容全部来自官方资料、引用完整或未引入外部推断。实践指南的命令、"
    "配置、预期结果和排错结论只能在绑定证据正文明确支持时生成；证据只说明原理时，"
    "改写为不含额外技术结论的说明性步骤。"
    "环境准备应写成条件式前提，不得声称学习者当前环境已经具备某项能力；"
    "验收标准应描述学习者需要完成的记录、核对或提交动作，不得声称这些动作已经发生。"
    "允许根据学习者画像调整讲授顺序、难度、解释粒度、示例组织和练习形式，但不得因此"
    "增加 retrieved_knowledge 之外的技术事实。生成正文前先在内部逐字段建立"
    "字段—事实—source_ref_id 映射；纯教学动作可以不作为事实，但混合句中的技术结论"
    "仍必须有直接来源。"
)
SOURCE_REPAIR_PROMPT = (
    "你是 V3 内容生成智能体的来源引用纠错步骤。只修复输入候选资源中不合法的"
    "source_ref_ids，并删除或重写无法由合法检索证据支持的内容。只能逐字复制"
    "allowed_source_ref_ids 中的值，禁止用知识点 ID、标题、URL 或自行构造的 ID 替代。"
    "保持资源类型不变，只返回符合给定 JSON Schema 的数据。summary 不得包含来源完整性"
    "或未引入外部推断的自述；命令、预期结果和排错结论必须由绑定证据正文直接支持。"
)
COVERAGE_REPAIR_PROMPT = (
    "你是 V3 内容生成智能体的定向覆盖补写步骤。编辑现有候选资源，只补充"
    "missing_knowledge_ids 对应的实质教学内容及其合法来源引用，同时完整保留"
    "preserve_knowledge_ids 已有内容。不得重写无关章节、不得删除已有合法来源，"
    "只能使用输入中的 allowed_source_ref_ids，并返回完整且符合 JSON Schema 的资源。不得补写"
    "来源完整性自述；命令、预期结果和排错结论必须由绑定证据正文直接支持。"
)
CONTENT_POLICY_REPAIR_PROMPT = (
    "你是 V3 内容生成智能体的内容策略修复步骤。只重写 policy_violations 指定的字段，"
    "删除生成过程、资料权威性、引用完整性或未引入外部推断的自述。summary 必须改为"
    "对已讲授知识结论的简短总结。version_boundary_missing 要删除具体版本限制；"
    "environment_evidence_missing 要将对应环境要求改为不含具体工具或配置断言的受控环境说明；"
    "operation_evidence_missing 要将 instruction 改为只观察或学习证据所述概念的说明性步骤；"
    "executable_evidence_missing 要将 code_or_command 设为 null 并保留不新增事实的说明性步骤；"
    "expected_result_evidence_missing 要将 expected_result 改为记录实际结果并与引用材料核对，"
    "不得声称固定输出；error_evidence_missing 要将 troubleshooting 设为 null。"
    "acceptance_evidence_missing 要将验收项改为学习记录或对比清单，不得保留技术结果断言。"
    "其他字段和合法引用必须保持不变，"
    "只返回符合 JSON Schema 的完整资源。"
)
REVISION_PROMPT = (
    "你是内容生成智能体的候选资源局部修订步骤。candidate 是上一轮资源，"
    "只能修改 revision_field_paths 指向的事实字段，并使用 retrieved_knowledge 中的直接证据。"
    "未点名字段必须原样保留；不得新增章节、步骤、题目、声明或来源。"
    "无直接证据时，删除无依据的技术结论，但保留合理的教学动作；环境前提使用条件式表达，"
    "验收项使用学习者待完成的记录、核对或提交动作，不得声称当前环境状态或动作已经发生。"
    "只返回完整且符合 JSON Schema 的候选资源。"
)
QUIZ_REPAIR_PROMPT = (
    "你是分级测验的局部修复步骤。仅重写 quiz_violations 指出的题目槽位；"
    "preserve_question_ids 中的题目必须逐字保留。每个槽位的 question_id、level、"
    "question_type、knowledge_id、difficulty 和 allowed_source_ref_ids 必须与 quiz_blueprint 一致。"
    "只返回完整且符合给定 JSON Schema 的测验。"
)
MAX_SOURCE_REPAIR_ATTEMPTS = 1
MAX_COVERAGE_REPAIR_ATTEMPTS = 1
MAX_CONTENT_POLICY_REPAIR_ATTEMPTS = 1

_PROVENANCE_META_PATTERNS = (
    re.compile(
        r"(?:所有|全部|以上|本(?:讲义|资源|内容)).{0,24}(?:均|都|严格)?(?:源自|来自|基于|依据).{0,24}(?:官方|所列|引用|检索)(?:文档|资料|来源|证据)"
    ),
    re.compile(r"(?:未|没有)(?:引入|使用).{0,16}(?:外部常识|外部知识|工具能力|额外推断|自行推断)"),
    re.compile(r"(?:引用|来源).{0,12}(?:完整|齐全|全部覆盖|均可追溯)"),
)


class GenerationError(RuntimeError):
    """Controlled error raised at the V3 generation boundary."""


class GeneratedContentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    structured_content: StructuredResourceContent
    difficulty: int


class LectureGenerationResponse(BaseModel):
    """Internal response shape for a lecture-only model call."""

    model_config = ConfigDict(extra="forbid")
    structured_content: LectureContent
    difficulty: int


class PracticeGuideGenerationResponse(BaseModel):
    """Internal response shape for a practice-guide-only model call."""

    model_config = ConfigDict(extra="forbid")
    structured_content: PracticeGuideContent
    difficulty: int


class GradedQuizGenerationResponse(BaseModel):
    """Internal response shape for a graded-quiz-only model call."""

    model_config = ConfigDict(extra="forbid")
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
    ) -> None:
        self._model = model if model is not None else settings.primary_llm_model
        self._gateway = model_gateway

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
            payload=_generation_payload(
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
    ) -> GeneratedContentResponse:
        revision_plan = request.requirements.revision_plan
        if revision_plan is None:
            raise GenerationError("revision_plan_required")
        response_model = _response_model_for(resource_type)
        result, metadata = self._gateway.complete_json(
            model=self._model,
            system_prompt=REVISION_PROMPT,
            payload=_generation_payload(
                request,
                resource_type,
                allowed_sources,
                candidate=candidate,
                correction_attempt=revision_plan.revision_count,
                response_model=response_model,
            ),
            fixture_factory=lambda: candidate.model_dump(mode="json"),
            response_model=response_model,
            max_output_tokens=_max_output_tokens_for(resource_type),
        )
        record_model_call(
            metadata,
            role="generation_model",
            resource_type=resource_type.value,
            correction_attempt=revision_plan.revision_count,
            correction_kind="field_revision",
        )
        return GeneratedContentResponse.model_validate(result)

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
            payload=_generation_payload(
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

    def repair_coverage(
        self,
        request: GenerateResourceInput,
        resource_type: ResourceType,
        allowed_sources: list[SourceRef],
        candidate: GeneratedContentResponse,
        missing_knowledge_ids: list[str],
        preserve_knowledge_ids: list[str],
    ) -> GeneratedContentResponse:
        fixture = _fixture_response(request, resource_type, allowed_sources)
        response_model = _response_model_for(resource_type)
        result, metadata = self._gateway.complete_json(
            model=self._model,
            system_prompt=COVERAGE_REPAIR_PROMPT,
            payload=_generation_payload(
                request,
                resource_type,
                allowed_sources,
                candidate=candidate,
                missing_knowledge_ids=missing_knowledge_ids,
                preserve_knowledge_ids=preserve_knowledge_ids,
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
            correction_attempt=1,
            correction_kind="coverage",
        )
        return GeneratedContentResponse.model_validate(result)

    def repair_content_policy(
        self,
        request: GenerateResourceInput,
        resource_type: ResourceType,
        allowed_sources: list[SourceRef],
        candidate: GeneratedContentResponse,
        violations: list[dict[str, str]],
    ) -> GeneratedContentResponse:
        fixture = _fixture_response(request, resource_type, allowed_sources)
        response_model = _response_model_for(resource_type)
        payload = _generation_payload(
            request,
            resource_type,
            allowed_sources,
            candidate=candidate,
            response_model=response_model,
        )
        payload["policy_violations"] = violations
        result, metadata = self._gateway.complete_json(
            model=self._model,
            system_prompt=CONTENT_POLICY_REPAIR_PROMPT,
            payload=payload,
            fixture_factory=lambda: fixture.model_dump(mode="json"),
            response_model=response_model,
            max_output_tokens=_max_output_tokens_for(resource_type),
        )
        record_model_call(
            metadata,
            role="generation_model",
            resource_type=resource_type.value,
            correction_attempt=1,
            correction_kind="content_policy",
        )
        return GeneratedContentResponse.model_validate(result)

    def repair_quiz(
        self,
        request: GenerateResourceInput,
        allowed_sources: list[SourceRef],
        candidate: GeneratedContentResponse,
        violations: list[dict[str, object]],
    ) -> GeneratedContentResponse:
        resource_type = ResourceType.GRADED_QUIZ
        fixture = _fixture_response(request, resource_type, allowed_sources)
        response_model = _response_model_for(resource_type)
        result, metadata = self._gateway.complete_json(
            model=self._model,
            system_prompt=QUIZ_REPAIR_PROMPT,
            payload=_generation_payload(
                request,
                resource_type,
                allowed_sources,
                candidate=candidate,
                response_model=response_model,
                quiz_violations=violations,
            ),
            fixture_factory=lambda: fixture.model_dump(mode="json"),
            response_model=response_model,
            max_output_tokens=_max_output_tokens_for(resource_type),
        )
        record_model_call(
            metadata,
            role="generation_model",
            resource_type=resource_type.value,
            correction_attempt=1,
            correction_kind="quiz_slots",
        )
        return GeneratedContentResponse.model_validate(result)


class ContentGenerationAgent:
    """Formal V3 boundary for personalized resource generation."""

    name = GENERATION_AGENT_NAME
    system_prompt = SYSTEM_PROMPT

    def __init__(
        self,
        generator: StructuredContentGenerator | None = None,
        logger: logging.Logger | None = None,
        renderer: Callable[[StructuredResourceContent, list[SourceRef]], str] | None = None,
    ) -> None:
        self._generator = generator or OpenAICompatibleStructuredGenerator()
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

    def _execute(
        self,
        request: GenerateResourceInput,
        candidates_by_type: dict[ResourceType, GeneratedResourceArtifact],
        audited_claims_by_type: dict[ResourceType, dict[str, list[str]]],
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
                raise GenerationError("generation_missing_target_evidence")
            sources_by_id = {
                chunk.source.source_ref_id: chunk.source for chunk in validated.retrieved_chunks
            }

            def generate_one(resource_type: ResourceType) -> GeneratedResourceArtifact:
                target_ids = set(validated.requirements.resource_knowledge_targets[resource_type])
                allowed_sources = [
                    chunk.source
                    for chunk in validated.retrieved_chunks
                    if chunk.source.source_ref_id in validated.requirements.source_whitelist
                    and chunk.knowledge_id in target_ids
                ]
                if not allowed_sources:
                    allowed_sources = [
                        sources_by_id[source_id]
                        for source_id in validated.requirements.source_whitelist
                    ]
                previous_candidate = candidates_by_type.get(resource_type)
                if previous_candidate is None:
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
                            GeneratedContentResponse.model_validate(
                                revise(
                                    validated,
                                    resource_type,
                                    allowed_sources,
                                    candidate_response,
                                )
                            )
                            if callable(revise)
                            else candidate_response
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
                        proposed = candidate_response
                    response = _merge_revision_candidate(
                        candidate_response,
                        proposed,
                        validated.requirements.revision_plan.field_paths_by_resource.get(
                            resource_type, []
                        ),
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

                for attempt in range(MAX_CONTENT_POLICY_REPAIR_ATTEMPTS + 1):
                    policy_violations = [
                        *_content_policy_violations(response.structured_content),
                        *_evidence_depth_violations(
                            response.structured_content,
                            validated,
                            allowed_sources,
                        ),
                    ]
                    if not policy_violations:
                        break
                    if attempt == MAX_CONTENT_POLICY_REPAIR_ATTEMPTS:
                        fallback_content = _apply_content_policy_fallback(
                            response.structured_content, policy_violations
                        )
                        response = response.model_copy(
                            update={"structured_content": fallback_content}
                        )
                        policy_violations = [
                            *_content_policy_violations(response.structured_content),
                            *_evidence_depth_violations(
                                response.structured_content,
                                validated,
                                allowed_sources,
                            ),
                        ]
                        if not policy_violations:
                            break
                        self._logger.warning(
                            "generation_content_policy_repair_exhausted task_id=%s "
                            "resource_type=%s violation_paths=%s",
                            validated.task_id,
                            resource_type.value,
                            [item["path"] for item in policy_violations],
                        )
                        raise GenerationError("generated_content_policy_invalid")
                    repair_policy = getattr(self._generator, "repair_content_policy", None)
                    if not callable(repair_policy):
                        raise GenerationError("generated_content_policy_invalid")
                    response = GeneratedContentResponse.model_validate(
                        repair_policy(
                            validated,
                            resource_type,
                            allowed_sources,
                            response,
                            policy_violations,
                        )
                    )
                if _source_violations(response.structured_content, whitelist):
                    raise GenerationError("generated_source_outside_whitelist_after_repair")

                if resource_type == ResourceType.GRADED_QUIZ:
                    blueprint = _quiz_blueprint(validated, allowed_sources)
                    quiz_violations = _quiz_blueprint_violations(
                        response.structured_content, blueprint
                    )
                    if quiz_violations:
                        repair_quiz = getattr(self._generator, "repair_quiz", None)
                        if not callable(repair_quiz):
                            raise GenerationError("graded_quiz_structure_invalid")
                        repaired = GeneratedContentResponse.model_validate(
                            repair_quiz(
                                validated,
                                allowed_sources,
                                response,
                                quiz_violations,
                            )
                        )
                        response = _merge_quiz_slot_repairs(response, repaired, quiz_violations)
                        quiz_violations = _quiz_blueprint_violations(
                            response.structured_content, blueprint
                        )
                    if quiz_violations:
                        self._logger.warning(
                            "graded_quiz_structure_invalid task_id=%s question_ids=%s fields=%s",
                            validated.task_id,
                            [item["question_id"] for item in quiz_violations],
                            [item["field"] for item in quiz_violations],
                        )
                        raise GenerationError("graded_quiz_structure_invalid")
                    violations = _source_violations(response.structured_content, whitelist)
                    if violations:
                        raise GenerationError("generated_source_outside_whitelist_after_repair")

                covered_before = _covered_knowledge_ids(
                    response.structured_content, validated, resource_type
                )
                missing = sorted(target_ids - covered_before)
                if missing:
                    repair_coverage = getattr(self._generator, "repair_coverage", None)
                    if callable(repair_coverage):
                        preserve = sorted(covered_before)
                        candidate = GeneratedContentResponse.model_validate(
                            repair_coverage(
                                validated,
                                resource_type,
                                allowed_sources,
                                response,
                                missing,
                                preserve,
                            )
                        )
                        violations = _source_violations(candidate.structured_content, whitelist)
                        covered_after = _covered_knowledge_ids(
                            candidate.structured_content, validated, resource_type
                        )
                        if not violations and covered_before.issubset(covered_after):
                            response = _merge_coverage_additions(
                                response,
                                candidate,
                                set(missing),
                                validated,
                            )

                covered_final = _covered_knowledge_ids(
                    response.structured_content, validated, resource_type
                )
                if target_ids - covered_final:
                    raise GenerationError("generated_coverage_incomplete")

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
                resources = [future.result() for future in futures]
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
        except (KeyError, ValidationError) as exc:
            self._log_failure(request, "invalid_generate_resource_output")
            raise GenerationError("invalid_generate_resource_output") from exc
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
    response_model: GenerationResponseModel | None = None,
    quiz_violations: list[dict[str, object]] | None = None,
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


def _claim_unit_count(value: object) -> int:
    if not isinstance(value, str):
        return 0
    return len([item for item in re.split(r"[。！？!?；;\n]+", value) if item.strip()])


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
            normalized = claim.strip().strip("。！？!?；;，,")
            if normalized and normalized in cleaned:
                cleaned = cleaned.replace(normalized, "", 1)
        cleaned = re.sub(r"^[\s。！？!?；;，,]+|[\s；;，,]+$", "", cleaned)
        cleaned = re.sub(r"([。！？!?；;，,])\s*[。！？!?；;，,]+", r"\1", cleaned)
        if cleaned != value:
            _write_path(payload, tokens, cleaned or _revision_fallback_text(parent))


def _revision_fallback_text(path: str) -> str:
    """Return non-factual prose when an audited field contains only a rejected claim."""
    if path.startswith("environment_requirements["):
        return "练习前请确认所需材料与受控环境已经准备妥当。"
    if path.startswith("acceptance_criteria["):
        return "完成练习后，提交学习记录并标注核对依据。"
    if path.endswith(".expected_result"):
        return "记录实际结果，并与引用材料中的描述进行核对。"
    if path.endswith(".instruction"):
        return "阅读引用材料，整理其中明确描述的处理流程。"
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


def _merge_coverage_additions(
    original: GeneratedContentResponse,
    proposed: GeneratedContentResponse,
    missing_knowledge_ids: set[str],
    request: GenerateResourceInput,
) -> GeneratedContentResponse:
    """Accept only new teaching blocks whose sources cover missing targets."""
    knowledge_by_source = {
        chunk.source.source_ref_id: chunk.knowledge_id for chunk in request.retrieved_chunks
    }

    def covers_missing(source_ids: list[str]) -> bool:
        return any(
            knowledge_by_source.get(source_id) in missing_knowledge_ids
            for source_id in source_ids
        )

    current = original.structured_content
    candidate = proposed.structured_content
    if isinstance(current, LectureContent) and isinstance(candidate, LectureContent):
        existing = {repr(item.model_dump(mode="python")) for item in current.core_concepts}
        additions = [
            item
            for item in candidate.core_concepts
            if repr(item.model_dump(mode="python")) not in existing
            and covers_missing(item.source_ref_ids)
        ]
        content = current.model_copy(
            update={"core_concepts": [*current.core_concepts, *additions][:20]}
        )
    elif isinstance(current, PracticeGuideContent) and isinstance(
        candidate, PracticeGuideContent
    ):
        existing = {repr(item.model_dump(mode="python")) for item in current.steps}
        additions = [
            item
            for item in candidate.steps
            if repr(item.model_dump(mode="python")) not in existing
            and covers_missing(item.source_ref_ids)
        ]
        steps = [
            item.model_copy(update={"order": index})
            for index, item in enumerate([*current.steps, *additions][:30], start=1)
        ]
        content = current.model_copy(update={"steps": steps})
    else:
        return original
    return GeneratedContentResponse(
        structured_content=content,
        difficulty=original.difficulty,
    )


def _content_policy_violations(
    content: StructuredResourceContent,
) -> list[dict[str, str]]:
    """Reject only explicit provenance/process self-claims, not technical prose."""
    values: list[tuple[str, str]] = []
    if isinstance(content, LectureContent):
        values.append(("summary", content.summary))
        values.extend(
            (f"core_concepts[{index}].explanation", block.explanation)
            for index, block in enumerate(content.core_concepts)
        )
        values.extend(
            (f"core_concepts[{index}].example", block.example)
            for index, block in enumerate(content.core_concepts)
            if block.example
        )
    elif isinstance(content, PracticeGuideContent):
        values.extend(
            (f"steps[{index}].instruction", step.instruction)
            for index, step in enumerate(content.steps)
        )
    else:
        values.extend(
            (f"questions[{index}].explanation", question.explanation)
            for index, question in enumerate(content.questions)
        )
    return [
        {"path": path, "code": "provenance_meta_claim"}
        for path, value in values
        if any(pattern.search(value) for pattern in _PROVENANCE_META_PATTERNS)
    ]


def _evidence_depth_violations(
    content: StructuredResourceContent,
    request: GenerateResourceInput,
    allowed_sources: list[SourceRef],
) -> list[dict[str, str]]:
    if not isinstance(content, PracticeGuideContent):
        return []
    chunks_by_source = {chunk.source.source_ref_id: chunk for chunk in request.retrieved_chunks}
    policy = get_domain_evidence_policy(request.context.domain_code)

    def capabilities(source_ids: list[str]) -> set[EvidenceCapability]:
        result: set[EvidenceCapability] = set()
        for source_id in source_ids:
            chunk = chunks_by_source.get(source_id)
            if chunk is not None:
                result.update(policy.classify(chunk))
        return result

    violations: list[dict[str, str]] = []
    all_capabilities = capabilities([source.source_ref_id for source in allowed_sources])
    if EvidenceCapability.OPERATION not in all_capabilities:
        for index, requirement in enumerate(content.environment_requirements):
            if "与引用材料相符" in requirement:
                continue
            violations.append(
                {
                    "path": f"environment_requirements[{index}]",
                    "code": "environment_evidence_missing",
                }
            )
    if EvidenceCapability.VERSION_BOUNDARY not in all_capabilities:
        for index, requirement in enumerate(content.environment_requirements):
            if re.search(r"\b\d+(?:\.\d+)+(?:\+|以上|以下)?\b", requirement):
                violations.append(
                    {
                        "path": f"environment_requirements[{index}]",
                        "code": "version_boundary_missing",
                    }
                )
    if EvidenceCapability.EXPECTED_RESULT not in all_capabilities:
        for index, criterion in enumerate(content.acceptance_criteria):
            if re.search(
                r"返回|输出|显示|生成|状态码|字段|自动|固定|成功状态|失败状态|"
                r"版本|命令|代码|接口响应",
                criterion,
            ):
                violations.append(
                    {
                        "path": f"acceptance_criteria[{index}]",
                        "code": "acceptance_evidence_missing",
                    }
                )
    for index, step in enumerate(content.steps):
        step_capabilities = capabilities(step.source_ref_ids)
        if EvidenceCapability.OPERATION not in step_capabilities and re.search(
            r"执行|运行|安装|配置|提交|调用|请求|创建|启动|输入命令|设置", step.instruction
        ):
            violations.append(
                {
                    "path": f"steps[{index}].instruction",
                    "code": "operation_evidence_missing",
                }
            )
        if step.code_or_command and not step_capabilities.intersection(
            {EvidenceCapability.COMMAND, EvidenceCapability.CODE_EXAMPLE}
        ):
            violations.append(
                {
                    "path": f"steps[{index}].code_or_command",
                    "code": "executable_evidence_missing",
                }
            )
        if step.troubleshooting and EvidenceCapability.ERROR_HANDLING not in step_capabilities:
            violations.append(
                {
                    "path": f"steps[{index}].troubleshooting",
                    "code": "error_evidence_missing",
                }
            )
        safe_observation = "记录实际结果" in step.expected_result and "引用材料" in step.expected_result
        if EvidenceCapability.EXPECTED_RESULT not in step_capabilities and not safe_observation:
            violations.append(
                {
                    "path": f"steps[{index}].expected_result",
                    "code": "expected_result_evidence_missing",
                }
            )
    return violations


def _apply_practice_evidence_fallback(
    content: StructuredResourceContent,
    violations: list[dict[str, str]],
) -> StructuredResourceContent:
    """Deterministically remove unsupported operational detail after model repair."""
    if not isinstance(content, PracticeGuideContent):
        return content

    codes_by_path: dict[str, set[str]] = {}
    for violation in violations:
        codes_by_path.setdefault(violation["path"], set()).add(violation["code"])

    environment_requirements = list(content.environment_requirements)
    for index in range(len(environment_requirements)):
        path = f"environment_requirements[{index}]"
        if codes_by_path.get(path, set()).intersection(
            {"environment_evidence_missing", "version_boundary_missing"}
        ):
            environment_requirements[index] = "与引用材料相符的受控学习环境"

    acceptance_criteria = list(content.acceptance_criteria)
    for index in range(len(acceptance_criteria)):
        path = f"acceptance_criteria[{index}]"
        if "acceptance_evidence_missing" in codes_by_path.get(path, set()):
            acceptance_criteria[index] = "形成学习记录并标注所依据的材料。"

    steps = []
    for index, step in enumerate(content.steps):
        updates: dict[str, str | None] = {}
        if "operation_evidence_missing" in codes_by_path.get(
            f"steps[{index}].instruction", set()
        ):
            updates["instruction"] = "阅读并梳理引用材料中明确描述的处理流程。"
        if "expected_result_evidence_missing" in codes_by_path.get(
            f"steps[{index}].expected_result", set()
        ):
            updates["expected_result"] = "记录实际结果并与引用材料中的描述进行核对。"
        if "executable_evidence_missing" in codes_by_path.get(
            f"steps[{index}].code_or_command", set()
        ):
            updates["code_or_command"] = None
        if "error_evidence_missing" in codes_by_path.get(
            f"steps[{index}].troubleshooting", set()
        ):
            updates["troubleshooting"] = None
        steps.append(step.model_copy(update=updates) if updates else step)

    return content.model_copy(
        update={
            "environment_requirements": environment_requirements,
            "acceptance_criteria": acceptance_criteria,
            "steps": steps,
        }
    )


def _apply_content_policy_fallback(
    content: StructuredResourceContent,
    violations: list[dict[str, str]],
) -> StructuredResourceContent:
    """Remove policy-only provenance self-claims without relaxing factual safeguards."""
    provenance_paths = {
        item["path"] for item in violations if item["code"] == "provenance_meta_claim"
    }
    sanitized = _sanitize_provenance_meta_claims(content, provenance_paths)
    return _apply_practice_evidence_fallback(sanitized, violations)


def _sanitize_provenance_text(value: str, fallback: str | None) -> str | None:
    """Drop only sentences that make unsupported claims about the resource itself."""
    sentences = re.findall(r"[^。！？!?；;\n]+[。！？!?；;\n]*", value)
    kept = [
        sentence.strip()
        for sentence in sentences
        if sentence.strip()
        and not any(pattern.search(sentence) for pattern in _PROVENANCE_META_PATTERNS)
    ]
    cleaned = "".join(kept).strip(" \t\r\n。！？!?；;")
    if cleaned:
        return cleaned
    return fallback


def _sanitize_provenance_meta_claims(
    content: StructuredResourceContent,
    paths: set[str],
) -> StructuredResourceContent:
    """Keep valid teaching text and fill required fields only when all text was removed."""
    if not paths:
        return content

    if isinstance(content, LectureContent):
        summary = content.summary
        if "summary" in paths:
            summary = _sanitize_provenance_text(
                summary,
                "请结合本讲义的核心概念，梳理关键要点并记录自己的理解。",
            )

        concepts = []
        for index, block in enumerate(content.core_concepts):
            explanation = block.explanation
            example = block.example
            explanation_path = f"core_concepts[{index}].explanation"
            example_path = f"core_concepts[{index}].example"
            if explanation_path in paths:
                explanation = _sanitize_provenance_text(
                    explanation,
                    "请阅读对应材料，梳理其中明确说明的关键概念。",
                )
            if example is not None and example_path in paths:
                example = _sanitize_provenance_text(example, None)
            concepts.append(
                block.model_copy(update={"explanation": explanation, "example": example})
            )
        return content.model_copy(update={"summary": summary, "core_concepts": concepts})

    if isinstance(content, GradedQuizContent):
        questions = []
        for index, question in enumerate(content.questions):
            path = f"questions[{index}].explanation"
            explanation = question.explanation
            if path in paths:
                explanation = _sanitize_provenance_text(
                    explanation,
                    "请结合题干和所列信息，重新梳理判断依据。",
                )
            questions.append(question.model_copy(update={"explanation": explanation}))
        return content.model_copy(update={"questions": questions})

    return content


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
    request: GenerateResourceInput, allowed_sources: list[SourceRef]
) -> list[dict[str, object]]:
    """Fix quiz slots deterministically; the model only fills assessment prose."""
    targets = request.requirements.resource_knowledge_targets[ResourceType.GRADED_QUIZ]
    source_ids_by_knowledge: dict[str, list[str]] = {}
    for source in allowed_sources:
        source_ids_by_knowledge.setdefault(source.knowledge_id, []).append(source.source_ref_id)
    reference_ids_by_knowledge: dict[str, list[str]] = {}
    for question in request.reference_questions:
        reference_ids_by_knowledge.setdefault(question.knowledge_id, []).append(question.question_id)
    slots = [
        (QuizLevel.FOUNDATION, QuestionType.SINGLE_CHOICE, -1),
        (QuizLevel.FOUNDATION, QuestionType.SHORT_ANSWER, -1),
        (QuizLevel.IMPROVEMENT, QuestionType.SINGLE_CHOICE, 0),
        (QuizLevel.IMPROVEMENT, QuestionType.SHORT_ANSWER, 0),
        (QuizLevel.CHALLENGE, QuestionType.MULTIPLE_CHOICE, 1),
        (QuizLevel.CHALLENGE, QuestionType.SHORT_ANSWER, 1),
    ]
    blueprint: list[dict[str, object]] = []
    for index, (level, question_type, offset) in enumerate(slots, start=1):
        knowledge_id = targets[(index - 1) % len(targets)]
        blueprint.append(
            {
                "question_id": f"Q{index}",
                "level": level.value,
                "question_type": question_type.value,
                "knowledge_id": knowledge_id,
                "difficulty": min(5, max(1, request.requirements.target_difficulty + offset)),
                "allowed_source_ref_ids": source_ids_by_knowledge[knowledge_id],
                "reference_question_ids": reference_ids_by_knowledge.get(knowledge_id, [])[:3],
            }
        )
    return blueprint


def _quiz_blueprint_violations(
    content: StructuredResourceContent, blueprint: list[dict[str, object]]
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
    return violations


def _merge_quiz_slot_repairs(
    original: GeneratedContentResponse,
    repaired: GeneratedContentResponse,
    violations: list[dict[str, object]],
) -> GeneratedContentResponse:
    if not isinstance(original.structured_content, GradedQuizContent) or not isinstance(
        repaired.structured_content, GradedQuizContent
    ):
        return repaired
    invalid_ids = {
        str(item["question_id"]) for item in violations if str(item["question_id"]).startswith("Q")
    }
    if "<package>" in {str(item["question_id"]) for item in violations}:
        return repaired
    repaired_by_id = {
        question.question_id: question for question in repaired.structured_content.questions
    }
    questions = [
        repaired_by_id.get(question.question_id, question)
        if question.question_id in invalid_ids
        else question
        for question in original.structured_content.questions
    ]
    content = original.structured_content.model_copy(update={"questions": questions})
    return original.model_copy(update={"structured_content": content})


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
                    "explanation": f"答案依据来源 {slot['allowed_source_ref_ids'][0]}。",
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
