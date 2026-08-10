"""V2 content generation Agent with structured generation and deterministic rendering."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from collections.abc import Callable
from typing import Protocol

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
from app.agents.v2_observability import record_model_call
from app.core.config import settings
from app.services.llm_service import OpenAICompatibleGateway, gateway


GENERATION_AGENT_NAME = "content_generation_agent_v2"
SYSTEM_PROMPT = (
    "你是 V2 内容生成智能体。必须仅使用输入中的检索证据和来源白名单，按指定资源类型"
    "生成结构化教学内容。不得编造来源、知识点或学习者信息；所有事实性内容必须关联"
    "source_ref_ids。只返回符合给定 JSON Schema 的数据，不负责审核或发布决策。"
)


class V2GenerationError(RuntimeError):
    """Controlled error raised at the V2 generation boundary."""


class GeneratedContentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    structured_content: StructuredResourceContent
    difficulty: int


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
        result, metadata = self._gateway.complete_json(
            model=self._model,
            system_prompt=SYSTEM_PROMPT,
            payload=_generation_payload(request, resource_type, allowed_sources),
            fixture_factory=lambda: fixture.model_dump(mode="json"),
            response_model=GeneratedContentResponse,
        )
        record_model_call(
            metadata,
            role="generation_model",
            resource_type=resource_type.value,
        )
        return GeneratedContentResponse.model_validate(result)


class V2ContentGenerationAgent:
    """Formal V2 boundary for personalized resource generation."""

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
        if not isinstance(request, GenerateResourceInput):
            self._logger.warning("generation_rejected error_code=invalid_generate_input_type")
            raise V2GenerationError("invalid_generate_input_type")

        try:
            validated = GenerateResourceInput.model_validate(request.model_dump(mode="python"))
            if self._renderer is None:
                raise V2GenerationError("generation_renderer_not_configured")
            sources_by_id = {
                chunk.source.source_ref_id: chunk.source for chunk in validated.retrieved_chunks
            }
            allowed_sources = [
                sources_by_id[source_id]
                for source_id in validated.requirements.source_whitelist
            ]

            def generate_one(resource_type: ResourceType) -> GeneratedResourceArtifact:
                response = GeneratedContentResponse.model_validate(
                    self._generator.generate(validated, resource_type, allowed_sources)
                )
                if response.structured_content.resource_type != resource_type.value:
                    raise V2GenerationError("generated_resource_type_mismatch")

                used_source_ids = structured_source_ref_ids(response.structured_content)
                whitelist = set(validated.requirements.source_whitelist)
                if not used_source_ids or not used_source_ids.issubset(whitelist):
                    raise V2GenerationError("generated_source_outside_whitelist")
                source_refs = [
                    sources_by_id[source_id]
                    for source_id in validated.requirements.source_whitelist
                    if source_id in used_source_ids
                ]
                return GeneratedResourceArtifact(
                    resource_type=resource_type,
                    structured_content=response.structured_content,
                    content_md=self._renderer(
                        response.structured_content, source_refs
                    ),
                    difficulty=response.difficulty,
                    source_refs=source_refs,
                )

            resource_types = validated.requirements.resource_types
            # ContextVars do not automatically cross executor threads.  Copy the
            # task-scoped collector so every resource generation is recorded.
            contexts = [copy_context() for _ in resource_types]
            with ThreadPoolExecutor(max_workers=len(resource_types)) as executor:
                futures = [
                    executor.submit(context.run, generate_one, resource_type)
                    for context, resource_type in zip(contexts, resource_types, strict=True)
                ]
                resources = [future.result() for future in futures]
            output = GenerateResourceOutput(task_id=validated.task_id, resources=resources)
        except V2GenerationError:
            self._log_failure(request, "generation_policy_rejected")
            raise
        except (KeyError, ValidationError) as exc:
            self._log_failure(request, "invalid_generate_resource_output")
            raise V2GenerationError("invalid_generate_resource_output") from exc
        except Exception as exc:
            self._log_failure(request, "generation_execution_failed")
            raise V2GenerationError("generation_execution_failed") from exc

        self._logger.info(
            "generation_completed task_id=%s resource_types=%s source_count=%s",
            output.task_id,
            [resource.resource_type for resource in output.resources],
            len(allowed_sources),
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
) -> dict[str, object]:
    chunks_by_source = {
        chunk.source.source_ref_id: chunk for chunk in request.retrieved_chunks
    }
    return {
        "task_id": request.task_id,
        "resource_type": resource_type.value,
        "profile": request.profile.model_dump(mode="json"),
        "requirements": request.requirements.model_dump(mode="json"),
        "retrieved_knowledge": [
            chunks_by_source[source.source_ref_id].model_dump(mode="json")
            for source in allowed_sources
        ],
        "output_schema": GeneratedContentResponse.model_json_schema(),
    }


def _fixture_response(
    request: GenerateResourceInput,
    resource_type: ResourceType,
    allowed_sources: list[SourceRef],
) -> GeneratedContentResponse:
    chunks_by_source = {
        chunk.source.source_ref_id: chunk for chunk in request.retrieved_chunks
    }
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
            environment_requirements=["Python 3.12"],
            steps=[
                {
                    "order": 1,
                    "title": f"验证{first_chunk.name}",
                    "instruction": first_chunk.content,
                    "expected_result": "操作结果与检索证据描述一致。",
                    "source_ref_ids": source_ids,
                }
            ],
            acceptance_criteria=["能够复现实操并指出所用知识来源。"],
        )
    else:
        questions = []
        levels = [QuizLevel.FOUNDATION, QuizLevel.IMPROVEMENT, QuizLevel.CHALLENGE]
        for index in range(6):
            level = levels[index // 2]
            questions.append(
                {
                    "question_id": f"Q{index + 1}",
                    "level": level,
                    "question_type": QuestionType.SHORT_ANSWER,
                    "prompt": f"说明{first_chunk.name}的关键点 {index + 1}。",
                    "correct_answer": first_chunk.content[:1000],
                    "explanation": f"答案依据来源 {first_source.source_ref_id}。",
                    "knowledge_id": first_chunk.knowledge_id,
                    "difficulty": min(5, max(1, difficulty + index // 2 - 1)),
                    "source_ref_ids": source_ids,
                }
            )
        content = GradedQuizContent(
            title=title,
            target_audience=audience,
            learning_objectives=[f"分层检验对{first_chunk.name}的掌握程度"],
            questions=questions,
        )

    return GeneratedContentResponse(structured_content=content, difficulty=difficulty)
