from __future__ import annotations

import pytest

from app.agents.contract_adapters import render_resource_markdown
from app.agents.contract_examples import initial_generation_flow_example
from app.agents.contracts import (
    GenerateResourceInput,
    GeneratedResourceArtifact,
    GenerationRequirements,
    ConceptBlock,
    GradedQuizContent,
    LectureContent,
    PracticeGuideContent,
    QuestionType,
    RetrievedQuestion,
    ResourceType,
    RevisionPlan,
)
from app.agents.generation_agent import (
    GeneratedContentResponse,
    ContentGenerationAgent,
    GenerationError,
    RevisionFieldPatch,
    RevisionPatchResponse,
    _apply_revision_patches,
    _sanitize_revision_patches,
    _generation_payload,
    _quiz_blueprint,
    _quiz_blueprint_violations,
    _fixture_response,
    _content_policy_violations,
    _merge_revision_candidate,
    _normalize_revision_path,
    _revision_field_fingerprints,
    _strip_audited_claims_after_repairs,
    normalize_generated_content,
)
from app.agents.observability import collect_model_calls
from app.agents.review_claim_manifest import build_review_claims
from app.agents.nodes import _merge_revision_retrieval, _partial_generation_input
from app.agents.domain_evidence_policy import (
    EvidenceCapability,
    get_domain_evidence_policy,
    normalize_evidence_capabilities,
)
from app.services.llm_service import ModelResponseError
from app.services.question_bank_service import (
    QuestionBankError,
    _eligible_question_values,
    _select_reference_questions,
    build_graded_quiz_from_question_bank,
)


def test_partial_revision_retains_sources_cited_by_unchanged_resources() -> None:
    flow = initial_generation_flow_example()
    previous = flow["retrieve_knowledge"]["output"]
    generated = flow["generate_resource"]["output"]
    fresh = previous.model_copy(
        update={
            "chunks": [previous.chunks[0]],
            "covered_knowledge_ids": [previous.chunks[0].knowledge_id],
        }
    )
    inherited_source_ids = {
        source.source_ref_id
        for resource in generated.resources
        if resource.resource_type is not ResourceType.GRADED_QUIZ
        for source in resource.source_refs
    }

    merged = _merge_revision_retrieval(
        previous=previous,
        fresh=fresh,
        generated=generated,
        active_types={ResourceType.GRADED_QUIZ},
    )

    merged_source_ids = {chunk.source.source_ref_id for chunk in merged.chunks}
    assert inherited_source_ids.issubset(merged_source_ids)
    assert {chunk.source.source_ref_id for chunk in fresh.chunks}.issubset(
        merged_source_ids
    )


class StubGenerator:
    def generate(self, request, resource_type, allowed_sources):
        source_ids = [source.source_ref_id for source in allowed_sources]
        return GeneratedContentResponse(
            structured_content=LectureContent(
                title="RAG 来源追溯讲义",
                target_audience=request.profile.profile_type.value,
                learning_objectives=["理解来源追溯"],
                core_concepts=[
                    {
                        "title": "来源追溯",
                        "explanation": request.retrieved_chunks[0].content,
                        "source_ref_ids": source_ids,
                    }
                ],
                summary="生成内容必须绑定检索来源。",
            ),
            difficulty=request.requirements.target_difficulty,
        )


class ForeignSourceGenerator(StubGenerator):
    def generate(self, request, resource_type, allowed_sources):
        response = super().generate(request, resource_type, allowed_sources)
        content = response.structured_content.model_copy(deep=True)
        content.core_concepts[0].source_ref_ids = ["foreign::chunk::0"]
        return response.model_copy(update={"structured_content": content})


class ContentPolicyRepairGenerator(StubGenerator):
    repair_calls = 0

    def generate(self, request, resource_type, allowed_sources):
        response = super().generate(request, resource_type, allowed_sources)
        content = response.structured_content.model_copy(deep=True)
        content.summary = "所有结论均源自所列官方文档，未引入外部常识。"
        return response.model_copy(update={"structured_content": content})

    def repair_content_policy(
        self, _request, _resource_type, _allowed_sources, candidate, violations
    ):
        self.repair_calls += 1
        assert violations == [{"path": "summary", "code": "forbidden_meta_claim"}]
        content = candidate.structured_content.model_copy(deep=True)
        content.summary = "RAG 资源应保留可追溯的来源引用。"
        return candidate.model_copy(update={"structured_content": content})


class UnrepairedContentPolicyGenerator(ContentPolicyRepairGenerator):
    def repair_content_policy(
        self, _request, _resource_type, _allowed_sources, candidate, _violations
    ):
        self.repair_calls += 1
        return candidate


class UnrepairedPracticeEvidenceGenerator:
    repair_calls = 0

    def generate(self, request, resource_type, allowed_sources):
        response = _fixture_response(request, resource_type, allowed_sources)
        content = response.structured_content.model_copy(deep=True)
        assert isinstance(content, PracticeGuideContent)
        content.environment_requirements[0] = "安装并配置 Python 3.12 环境"
        content.steps[0].instruction = "执行 Git 提交并调用 HTTP 接口"
        content.steps[0].code_or_command = "git commit -m test"
        content.steps[0].expected_result = "接口固定返回成功状态"
        content.steps[0].troubleshooting = "失败时重新提交"
        content.acceptance_criteria[0] = "接口返回固定 JSON 字段"
        return response.model_copy(update={"structured_content": content})

    def repair_content_policy(
        self, _request, _resource_type, _allowed_sources, candidate, _violations
    ):
        self.repair_calls += 1
        return candidate


class UnrepairedPracticeResultGenerator:
    repair_calls = 0

    def generate(self, request, resource_type, allowed_sources):
        response = _fixture_response(request, resource_type, allowed_sources)
        content = response.structured_content.model_copy(deep=True)
        assert isinstance(content, PracticeGuideContent)
        content.steps[0].expected_result = "接口固定返回成功状态"
        return response.model_copy(update={"structured_content": content})

    def repair_content_policy(
        self, _request, _resource_type, _allowed_sources, candidate, _violations
    ):
        self.repair_calls += 1
        return candidate


class UnrepairedPracticeProvenanceGenerator:
    repair_calls = 0

    def generate(self, request, resource_type, allowed_sources):
        response = _fixture_response(request, resource_type, allowed_sources)
        content = response.structured_content.model_copy(deep=True)
        assert isinstance(content, PracticeGuideContent)
        second = content.steps[0].model_copy(
            update={
                "order": 2,
                "instruction": "整理差异。所有结论均源自所列官方文档。",
            }
        )
        content.steps.append(second)
        return response.model_copy(update={"structured_content": content})

    def repair_content_policy(
        self, _request, _resource_type, _allowed_sources, candidate, _violations
    ):
        self.repair_calls += 1
        return candidate


class CandidateRevisionGenerator:
    revise_calls = 0

    def revise(self, _request, _resource_type, _allowed_sources, candidate):
        self.revise_calls += 1
        content = candidate.structured_content.model_copy(deep=True)
        assert isinstance(content, PracticeGuideContent)
        content.title = "不应覆盖的标题"
        content.steps[0].expected_result = "记录实际结果并与引用材料核对。"
        return candidate.model_copy(update={"structured_content": content, "difficulty": 5})


class InvalidCandidateRevisionGenerator:
    revise_calls = 0

    def revise(self, _request, resource_type, _allowed_sources, _candidate):
        self.revise_calls += 1
        raise ModelResponseError(
            "invalid structured output",
            metadata={
                "provider_mode": "live",
                "model_name": "test-model",
                "attempt_count": 2,
                "status": "failed",
                "validation_fields": ["structured_content.steps.0.expected_result"],
            },
        )


class CoverageRepairGenerator(StubGenerator):
    repair_calls = 0

    def generate(self, request, resource_type, allowed_sources):
        response = super().generate(request, resource_type, allowed_sources[:1])
        return response

    def repair_coverage(
        self,
        request,
        resource_type,
        allowed_sources,
        candidate,
        missing_knowledge_ids,
        preserve_knowledge_ids,
    ):
        self.repair_calls += 1
        content = candidate.structured_content.model_copy(deep=True)
        content.core_concepts.append(
            ConceptBlock(
                title="定向补写",
                explanation="补齐缺失目标并保持原有章节。",
                source_ref_ids=[allowed_sources[-1].source_ref_id],
            )
        )
        return candidate.model_copy(update={"structured_content": content})


class InvalidStructuredOutputGenerator:
    def generate(self, _request, _resource_type, _allowed_sources):
        raise ModelResponseError(
            "invalid structured output",
            metadata={
                "provider_mode": "live",
                "model_name": "test-model",
                "tokens_input": 120,
                "tokens_output": 80,
                "attempt_count": 2,
                "status": "failed",
                "validation_fields": ["structured_content.questions.5.options"],
                "duration_ms": 10,
            },
        )


class ResourceRetryGenerator:
    def __init__(self, *, persistent_failure: bool = False) -> None:
        self.calls = {ResourceType.LECTURE: 0, ResourceType.PRACTICE_GUIDE: 0}
        self.persistent_failure = persistent_failure

    def generate(self, request, resource_type, allowed_sources):
        self.calls[resource_type] += 1
        if resource_type is ResourceType.PRACTICE_GUIDE and (
            self.persistent_failure or self.calls[resource_type] == 1
        ):
            raise GenerationError("practice_structure_invalid")
        return _fixture_response(request, resource_type, allowed_sources)


class InvalidLocalStructureGenerator:
    def generate(self, _request, _resource_type, _allowed_sources):
        return {"difficulty": 2}


class QuizGeneratorMustNotRun:
    def generate(self, _request, _resource_type, _allowed_sources):
        raise AssertionError("正式题库组卷不得调用生成模型")

def _input() -> GenerateResourceInput:
    request = initial_generation_flow_example()["generate_resource"]["input"]
    requirements = request.requirements.model_copy(
        update={
            "resource_types": [ResourceType.LECTURE],
            "required_knowledge_ids": request.requirements.resource_knowledge_targets[
                ResourceType.LECTURE
            ],
            "resource_knowledge_targets": {
                ResourceType.LECTURE: request.requirements.resource_knowledge_targets[
                    ResourceType.LECTURE
                ]
            },
        }
    )
    return request.model_copy(update={"requirements": requirements})


def _with_formal_question_bank(request: GenerateResourceInput) -> GenerateResourceInput:
    target_ids = request.requirements.resource_knowledge_targets.get(
        ResourceType.GRADED_QUIZ, []
    )
    questions = []
    for knowledge_id in target_ids:
        source_locator = next(
            chunk.source_locator
            for chunk in request.retrieved_chunks
            if chunk.knowledge_id == knowledge_id
        )
        for slot in range(1, 7):
            is_choice = slot % 2 == 1
            questions.append(
                RetrievedQuestion(
                    question_id=f"formal_{knowledge_id}_{slot}",
                    knowledge_id=knowledge_id,
                    question_type=(
                        QuestionType.SINGLE_CHOICE
                        if is_choice
                        else QuestionType.SHORT_ANSWER
                    ),
                    stem=f"正式题库题目 {slot}",
                    options=["正确项", "干扰项一", "干扰项二", "干扰项三"]
                    if is_choice
                    else [],
                    answer_key={
                        **(
                            {"correct_option": 0}
                            if is_choice
                            else {"answer": "来源支持的答案", "rubric": ["评分点一", "评分点二"]}
                        ),
                        "explanation": "依据当前知识点来源材料判定。",
                        "source_ref_ids": [
                            next(
                                chunk.source.source_ref_id
                                for chunk in request.retrieved_chunks
                                if chunk.knowledge_id == knowledge_id
                                and chunk.source_locator == source_locator
                            )
                        ],
                        "source_locator": source_locator,
                        "question_slot": slot,
                        "quiz_level": (
                            "foundation"
                            if slot <= 2
                            else "improvement"
                            if slot <= 4
                            else "challenge"
                        ),
                    },
                    explanation="依据当前知识点来源材料判定。",
                    difficulty=min(5, max(1, slot)),
                )
            )
    return request.model_copy(update={"reference_questions": questions})


def test_formal_question_bank_allows_short_matching_quiz_but_requires_three_questions() -> None:
    request = initial_generation_flow_example()["generate_resource"]["input"]
    request = _with_formal_question_bank(request)
    incomplete = request.model_copy(update={"reference_questions": request.reference_questions[:-4]})

    with pytest.raises(QuestionBankError, match="graded_quiz_question_bank_insufficient"):
        _select_reference_questions(incomplete)


def test_formal_short_answer_accepts_detailed_source_backed_rubric() -> None:
    answer_key = {
        "answer": "来源支持的完整答案",
        "explanation": "来源支持的解析",
        "source_ref_ids": ["knowledge::chunk::0"],
        "quiz_level": "challenge",
        "rubric": [f"评分点 {index}" for index in range(8)],
    }

    assert _eligible_question_values("short_answer", [], answer_key)
    assert not _eligible_question_values(
        "short_answer", [], {**answer_key, "rubric": [*answer_key["rubric"], "评分点 9"]}
    )


def test_formal_question_bank_does_not_mix_unrelated_knowledge() -> None:
    request = initial_generation_flow_example()["generate_resource"]["input"]
    request = _with_formal_question_bank(request)
    unrelated = request.reference_questions[0].model_copy(
        update={"question_id": "foreign-question", "knowledge_id": "FOREIGN-K001"}
    )
    selected = _select_reference_questions(
        request.model_copy(update={"reference_questions": [*request.reference_questions, unrelated]})
    )

    assert all(question.knowledge_id != "FOREIGN-K001" for _, _, question in selected)


def test_formal_question_with_declared_locator_cannot_fall_back_to_other_chunk() -> None:
    request = _with_formal_question_bank(
        initial_generation_flow_example()["generate_resource"]["input"]
    )
    first = request.reference_questions[0].model_copy(
        update={
            "answer_key": {
                **request.reference_questions[0].answer_key,
                "source_locator": "missing-exact-locator",
            }
        }
    )
    request = request.model_copy(
        update={"reference_questions": [first, *request.reference_questions[1:]]}
    )

    with pytest.raises(QuestionBankError, match="graded_quiz_question_source_missing"):
        build_graded_quiz_from_question_bank(
            request,
            [chunk.source for chunk in request.retrieved_chunks],
        )


def test_quiz_only_revision_preserves_selected_related_question_source() -> None:
    request = _with_formal_question_bank(
        initial_generation_flow_example()["generate_resource"]["input"]
    )
    target_id = request.requirements.resource_knowledge_targets[ResourceType.GRADED_QUIZ][0]
    target_chunk = next(
        chunk for chunk in request.retrieved_chunks if chunk.knowledge_id == target_id
    )
    related_source_id = "RELATED-K001::chunk::0"
    related_locator = "document:related-question-source#chunk=0"
    related_chunk = target_chunk.model_copy(
        update={
            "knowledge_id": "RELATED-K001",
            "source_locator": related_locator,
            "source": target_chunk.source.model_copy(
                update={"source_ref_id": related_source_id}
            ),
        }
    )
    questions = [
        question.model_copy(
            update={
                "knowledge_id": "RELATED-K001",
                "related_knowledge_ids": [target_id],
                "answer_key": {
                    **question.answer_key,
                    "source_ref_ids": [related_source_id],
                    "source_locator": related_locator,
                },
            }
        )
        if question.knowledge_id == target_id
        else question
        for question in request.reference_questions
    ]
    request = request.model_copy(
        update={
            "retrieved_chunks": [*request.retrieved_chunks, related_chunk],
            "reference_questions": questions,
        }
    )

    partial = _partial_generation_input(request, [ResourceType.GRADED_QUIZ])

    assert related_source_id in partial.requirements.source_whitelist
    content = build_graded_quiz_from_question_bank(
        partial, [chunk.source for chunk in partial.retrieved_chunks]
    )
    assert len(content.questions) == 3
    assert any(question.knowledge_id == "RELATED-K001" for question in content.questions)


def test_formal_quiz_revision_replaces_rejected_question_without_model_generation() -> None:
    request = _with_formal_question_bank(
        initial_generation_flow_example()["generate_resource"]["input"]
    )
    request = _partial_generation_input(request, [ResourceType.GRADED_QUIZ])
    replacement = request.reference_questions[2].model_copy(
        update={
            "question_id": "formal_replacement_improvement",
            "stem": "正式题库替代提升题",
        }
    )
    request = request.model_copy(
        update={"reference_questions": [*request.reference_questions, replacement]}
    )
    agent = ContentGenerationAgent(
        generator=QuizGeneratorMustNotRun(), renderer=render_resource_markdown
    )
    previous = agent.execute(request).resources[0]
    previous_content = previous.structured_content
    assert isinstance(previous_content, GradedQuizContent)
    rejected_id = previous_content.questions[2].question_id
    revision_plan = RevisionPlan(
        revision_count=1,
        resource_types=[ResourceType.GRADED_QUIZ],
        field_paths_by_resource={
            ResourceType.GRADED_QUIZ: ["questions[2].prompt"]
        },
    )
    revised_request = request.model_copy(
        update={
            "requirements": request.requirements.model_copy(
                update={"revision_plan": revision_plan}
            )
        }
    )

    revised = agent.revise(revised_request, [previous]).resources[0].structured_content

    assert isinstance(revised, GradedQuizContent)
    assert len(revised.questions) == 3
    assert rejected_id not in {question.question_id for question in revised.questions}
    assert all(question.reference_question_ids for question in revised.questions)


def test_v3_generation_emits_contract_artifact_and_deterministic_markdown() -> None:
    output = ContentGenerationAgent(
        generator=StubGenerator(), renderer=render_resource_markdown
    ).execute(_input())

    assert output.contract_version == "agent-contract-v10"
    assert output.task_id == _input().task_id
    assert [item.resource_type for item in output.resources] == [ResourceType.LECTURE]
    artifact = output.resources[0]
    assert artifact.content_md == render_resource_markdown(
        artifact.structured_content, artifact.source_refs
    )


def test_v3_generation_rejects_non_contract_input() -> None:
    with pytest.raises(GenerationError, match="invalid_generate_input_type"):
        ContentGenerationAgent(
            generator=StubGenerator(), renderer=render_resource_markdown
        ).execute({})  # type: ignore[arg-type]


def _lecture_and_practice_input() -> GenerateResourceInput:
    request = _input()
    resource_types = [ResourceType.LECTURE, ResourceType.PRACTICE_GUIDE]
    targets = request.requirements.required_knowledge_ids
    return request.model_copy(
        update={
            "context": request.context.model_copy(
                update={"requested_resource_types": resource_types}
            ),
            "requirements": request.requirements.model_copy(
                update={
                    "resource_types": resource_types,
                    "resource_knowledge_targets": {
                        resource_type: targets for resource_type in resource_types
                    },
                }
            ),
        }
    )


def test_parallel_generation_retries_only_failed_resource() -> None:
    generator = ResourceRetryGenerator()

    output = ContentGenerationAgent(
        generator=generator, renderer=render_resource_markdown
    ).execute(_lecture_and_practice_input())

    assert [item.resource_type for item in output.resources] == [
        ResourceType.LECTURE,
        ResourceType.PRACTICE_GUIDE,
    ]
    assert generator.calls == {
        ResourceType.LECTURE: 1,
        ResourceType.PRACTICE_GUIDE: 2,
    }


def test_parallel_generation_records_persistent_failed_resource(caplog) -> None:
    generator = ResourceRetryGenerator(persistent_failure=True)

    with pytest.raises(GenerationError, match="practice_structure_invalid"):
        ContentGenerationAgent(
            generator=generator, renderer=render_resource_markdown
        ).execute(_lecture_and_practice_input())

    assert generator.calls == {
        ResourceType.LECTURE: 1,
        ResourceType.PRACTICE_GUIDE: 2,
    }
    assert "generation_resource_failed" in caplog.text
    assert "practice_guide" in caplog.text


def test_missing_target_evidence_is_observable_but_does_not_block_review(caplog) -> None:
    request = _input()
    retained = request.retrieved_chunks[0]
    request = request.model_copy(
        update={
            "retrieved_chunks": [retained],
            "requirements": request.requirements.model_copy(
                update={"source_whitelist": [retained.source.source_ref_id]}
            ),
        }
    )

    output = ContentGenerationAgent(
        generator=StubGenerator(), renderer=render_resource_markdown
    ).execute(request)

    assert output.resources
    assert "generation_missing_target_evidence" in caplog.text


def test_v3_generation_rejects_sources_outside_whitelist() -> None:
    with pytest.raises(GenerationError, match="generated_source_outside_whitelist"):
        ContentGenerationAgent(
            generator=ForeignSourceGenerator(), renderer=render_resource_markdown
        ).execute(_input())


def test_generation_normalizes_forbidden_source_meta_claim_without_model_repair() -> None:
    generator = ContentPolicyRepairGenerator()
    output = ContentGenerationAgent(generator=generator, renderer=render_resource_markdown).execute(
        _input()
    )

    assert generator.repair_calls == 0
    content = output.resources[0].structured_content
    assert content.summary == "请结合本讲义的核心概念，梳理关键要点并记录自己的理解。"
    assert not _content_policy_violations(content)


def test_generation_downgrades_source_meta_claim_without_model_repair() -> None:
    generator = UnrepairedContentPolicyGenerator()
    output = ContentGenerationAgent(
        generator=generator, renderer=render_resource_markdown
    ).execute(_input())

    assert generator.repair_calls == 0
    content = output.resources[0].structured_content
    assert isinstance(content, LectureContent)
    assert content.summary == "请结合本讲义的核心概念，梳理关键要点并记录自己的理解。"
    assert not _content_policy_violations(content)












def test_quiz_content_policy_removes_internal_source_ids_from_all_fact_fields() -> None:
    request = _input()
    targets = [chunk.knowledge_id for chunk in request.retrieved_chunks]
    request = request.model_copy(
        update={
            "context": request.context.model_copy(
                update={"requested_resource_types": [ResourceType.GRADED_QUIZ]}
            ),
            "requirements": request.requirements.model_copy(
                update={
                    "resource_types": [ResourceType.GRADED_QUIZ],
                    "resource_knowledge_targets": {ResourceType.GRADED_QUIZ: targets},
                }
            ),
        }
    )
    request = _with_formal_question_bank(request)
    sources = [chunk.source for chunk in request.retrieved_chunks]
    content = _fixture_response(request, ResourceType.GRADED_QUIZ, sources).structured_content
    content = content.model_copy(deep=True)
    content.questions[0].prompt = "请依据 AIAPP-K029::chunk::0 作答。"
    content.questions[0].correct_answer = "答案来自 AIAPP-K029::chunk::0。"
    content.questions[0].explanation = "AIAPP-K029::chunk::0 明确支持该答案。"

    violations = _content_policy_violations(content)
    sanitized = normalize_generated_content(content)

    assert {item["path"] for item in violations} >= {
        "questions[0].prompt",
        "questions[0].correct_answer",
        "questions[0].explanation",
    }
    question = sanitized.questions[0]
    assert "::chunk::" not in question.prompt
    assert "::chunk::" not in question.correct_answer
    assert "::chunk::" not in question.explanation


def test_quiz_content_policy_drops_absence_based_distractor_reasoning() -> None:
    request = _input()
    targets = list(request.requirements.required_knowledge_ids)
    request = request.model_copy(
        update={
            "context": request.context.model_copy(
                update={"requested_resource_types": [ResourceType.GRADED_QUIZ]}
            ),
            "requirements": request.requirements.model_copy(
                update={
                    "resource_types": [ResourceType.GRADED_QUIZ],
                    "resource_knowledge_targets": {ResourceType.GRADED_QUIZ: targets},
                }
            ),
        }
    )
    request = _with_formal_question_bank(request)
    sources = [chunk.source for chunk in request.retrieved_chunks]
    content = _fixture_response(request, ResourceType.GRADED_QUIZ, sources).structured_content
    content = content.model_copy(deep=True)
    content.questions[0].explanation = (
        "HTTP 请求包含方法和目标 URI；RFC 未声明响应头字段可选；因此仅选前两项。"
    )

    violations = _content_policy_violations(content)
    sanitized = normalize_generated_content(content)

    assert any(item["code"] == "unsupported_distractor_rationale" for item in violations)
    assert sanitized.questions[0].explanation == "HTTP 请求包含方法和目标 URI；"


def test_lecture_explanation_is_not_treated_as_a_quiz_distractor_rationale() -> None:
    request = _input()
    sources = [chunk.source for chunk in request.retrieved_chunks]
    content = _fixture_response(request, ResourceType.LECTURE, sources).structured_content
    assert isinstance(content, LectureContent)
    content = content.model_copy(deep=True)
    content.core_concepts[0].explanation = "文档未说明响应头字段可选，因此应重点核对响应结构。"

    violations = _content_policy_violations(content)

    assert not any(
        item == {
            "path": "core_concepts[0].explanation",
            "code": "unsupported_distractor_rationale",
        }
        for item in violations
    )


def test_generation_leaves_fixed_practice_result_for_semantic_review() -> None:
    request = _input()
    requirements = request.requirements.model_copy(
        update={
            "resource_types": [ResourceType.PRACTICE_GUIDE],
            "resource_knowledge_targets": {
                ResourceType.PRACTICE_GUIDE: request.requirements.required_knowledge_ids
            },
        }
    )
    context = request.context.model_copy(
        update={"resource_types": [ResourceType.PRACTICE_GUIDE]}
    )
    generator = UnrepairedPracticeResultGenerator()

    output = ContentGenerationAgent(
        generator=generator, renderer=render_resource_markdown
    ).execute(request.model_copy(update={"context": context, "requirements": requirements}))

    assert generator.repair_calls == 0
    content = output.resources[0].structured_content
    assert isinstance(content, PracticeGuideContent)
    assert content.steps[0].expected_result == "接口固定返回成功状态"












def test_revision_path_normalizes_atomic_claim_suffixes() -> None:
    assert (
        _normalize_revision_path("summary[4]", ResourceType.LECTURE) == "summary"
    )
    assert _normalize_revision_path(
        "core_concepts[1].explanation[2]", ResourceType.LECTURE
    ) == "core_concepts[1].explanation"
    assert _normalize_revision_path(
        "steps[1].expected_result[0]", ResourceType.PRACTICE_GUIDE
    ) == "steps[1].expected_result"
    assert _normalize_revision_path(
        "steps[1].source_ref_ids[0]", ResourceType.PRACTICE_GUIDE
    ) is None


def test_revision_merge_changes_only_audited_field() -> None:
    request = _input()
    source = request.retrieved_chunks[0].source
    original = _fixture_response(request, ResourceType.PRACTICE_GUIDE, [source])
    proposed_content = original.structured_content.model_copy(deep=True)
    assert isinstance(proposed_content, PracticeGuideContent)
    proposed_content.title = "不应被接受的新标题"
    proposed_content.steps[0].instruction = "不应被接受的新操作。"
    proposed_content.steps[0].expected_result = "记录结果并核对材料。"
    proposed = original.model_copy(
        update={"structured_content": proposed_content, "difficulty": 5}
    )

    merged = _merge_revision_candidate(
        original,
        proposed,
        ["steps[0].expected_result[0]"],
    )

    assert isinstance(merged.structured_content, PracticeGuideContent)
    assert merged.structured_content.title == original.structured_content.title
    assert (
        merged.structured_content.steps[0].instruction
        == original.structured_content.steps[0].instruction
    )
    assert merged.structured_content.steps[0].expected_result == "记录结果并核对材料。"
    assert (
        merged.structured_content.steps[0].source_ref_ids
        == original.structured_content.steps[0].source_ref_ids
    )
    assert merged.difficulty == original.difficulty


def test_typed_revision_patch_preserves_structure_and_unrelated_fields() -> None:
    request = _input()
    source = request.retrieved_chunks[0].source
    original = _fixture_response(request, ResourceType.PRACTICE_GUIDE, [source])
    assert isinstance(original.structured_content, PracticeGuideContent)
    original_payload = original.structured_content.model_dump(mode="python")

    revised = _apply_revision_patches(
        original,
        RevisionPatchResponse(
            patches=[
                RevisionFieldPatch(
                    path="steps[0].expected_result",
                    value="记录结果并核对材料。",
                )
            ]
        ),
        ["steps[0].expected_result[0]"],
    )
    assert isinstance(revised.structured_content, PracticeGuideContent)
    assert revised.structured_content.steps[0].expected_result == "记录结果并核对材料。"
    revised_payload = revised.structured_content.model_dump(mode="python")
    revised_payload["steps"][0]["expected_result"] = original_payload["steps"][0][
        "expected_result"
    ]
    assert revised_payload == original_payload
    assert revised.difficulty == original.difficulty




def test_unrepaired_meta_claim_is_sanitized_without_rejecting_teaching_step() -> None:
    request = _input()
    requirements = request.requirements.model_copy(
        update={
            "resource_types": [ResourceType.PRACTICE_GUIDE],
            "resource_knowledge_targets": {
                ResourceType.PRACTICE_GUIDE: request.requirements.required_knowledge_ids
            },
        }
    )
    context = request.context.model_copy(
        update={"resource_types": [ResourceType.PRACTICE_GUIDE]}
    )
    generator = UnrepairedPracticeProvenanceGenerator()

    output = ContentGenerationAgent(
        generator=generator, renderer=render_resource_markdown
    ).execute(request.model_copy(update={"context": context, "requirements": requirements}))

    assert generator.repair_calls == 0
    content = output.resources[0].structured_content
    assert isinstance(content, PracticeGuideContent)
    assert content.steps[1].instruction == "整理差异"








def test_capability_normalization_accepts_only_canonical_domain_neutral_values() -> None:
    assert normalize_evidence_capabilities(
        ["definition", "code_example", "error_handling", "unknown"]
    ) == ["code_example", "concept", "error_handling"]
    policy = get_domain_evidence_policy(
        "arbitrary_domain", {"k1": ["operation", "expected_result"]}
    )
    assert policy.declared_by_knowledge == {
        "k1": frozenset(
            {
                EvidenceCapability.CONCEPT,
                EvidenceCapability.OPERATION,
                EvidenceCapability.EXPECTED_RESULT,
            }
        )
    }



def test_practice_revision_keeps_valid_field_patches_instead_of_cleaned_baseline() -> None:
    request = _input()
    source = request.retrieved_chunks[0].source
    original = _fixture_response(request, ResourceType.PRACTICE_GUIDE, [source])
    assert isinstance(original.structured_content, PracticeGuideContent)
    original_content = original.structured_content.model_copy(deep=True)
    original_content.environment_requirements[0] = "Python 3 环境固定满足运行要求"
    original_content.steps[0].expected_result = "接口固定返回成功状态"
    original = original.model_copy(update={"structured_content": original_content})

    revised = _apply_revision_patches(
        original,
        RevisionPatchResponse(
            patches=[
                RevisionFieldPatch(
                    path="environment_requirements[0]",
                    value="网络连通性支持访问目标接口",
                ),
                RevisionFieldPatch(
                    path="steps[0].expected_result",
                    value="运行后自动输出成功日志",
                ),
            ]
        ),
        ["environment_requirements[0][0]", "steps[0].expected_result[0]"],
        {
            "environment_requirements[0][0]": ["Python 3 环境固定满足运行要求"],
            "steps[0].expected_result[0]": ["接口固定返回成功状态"],
        },
    )

    content = revised.structured_content
    assert isinstance(content, PracticeGuideContent)
    assert content.environment_requirements[0] == "网络连通性支持访问目标接口"
    assert content.steps[0].expected_result == "运行后自动输出成功日志"


def test_practice_revision_preserves_replacement_for_followup_review() -> None:
    request = _input()
    source = request.retrieved_chunks[0].source
    original = _fixture_response(request, ResourceType.PRACTICE_GUIDE, [source])
    assert isinstance(original.structured_content, PracticeGuideContent)
    original_content = original.structured_content.model_copy(deep=True)
    rejected = "仅当状态码为 2xx 时才读取响应体"
    original_content.steps[0].instruction = rejected
    original = original.model_copy(update={"structured_content": original_content})

    revised = _apply_revision_patches(
        original,
        RevisionPatchResponse(
            patches=[
                RevisionFieldPatch(
                    path="steps[0].instruction",
                    value="仅当状态码为 2xx 且内容类型为 JSON 时才解析响应体",
                )
            ]
        ),
        ["steps[0].instruction[0]"],
        {"steps[0].instruction[0]": [rejected]},
    )

    assert isinstance(revised.structured_content, PracticeGuideContent)
    assert revised.structured_content.steps[0].instruction == (
        "仅当状态码为 2xx 且内容类型为 JSON 时才解析响应体"
    )


@pytest.mark.parametrize(
    "patches",
    [
        [RevisionFieldPatch(path="title", value="越权标题")],
        [
            RevisionFieldPatch(path="steps[0].expected_result", value="第一次修改。"),
            RevisionFieldPatch(path="steps[0].expected_result", value="重复修改。"),
        ],
        [
            RevisionFieldPatch(
                path="steps[0].expected_result",
                value="第一项新结论。第二项新结论。",
            )
        ],
    ],
)
def test_typed_revision_patch_rejects_illegal_or_non_monotonic_patch(patches) -> None:
    request = _input()
    source = request.retrieved_chunks[0].source
    original = _fixture_response(request, ResourceType.PRACTICE_GUIDE, [source])

    with pytest.raises(GenerationError, match="patch_validation_failed"):
        _apply_revision_patches(
            original,
            RevisionPatchResponse(patches=patches),
            ["steps[0].expected_result[0]"],
        )


def test_revision_patch_sanitizer_keeps_valid_fields_and_truncates_expansion() -> None:
    request = _input()
    source = request.retrieved_chunks[0].source
    original = _fixture_response(request, ResourceType.PRACTICE_GUIDE, [source])
    proposed = RevisionPatchResponse(
        patches=[
            RevisionFieldPatch(path="title", value="越权标题"),
            RevisionFieldPatch(
                path="steps[0].expected_result[0]",
                value="保留第一项受控结论。不得增加第二项事实。",
            ),
        ]
    )

    sanitized, rejected = _sanitize_revision_patches(
        original,
        proposed,
        ["steps[0].expected_result[0]"],
    )

    assert rejected == ["title"]
    assert sanitized.patches == [
        RevisionFieldPatch(
            path="steps[0].expected_result",
            value="保留第一项受控结论。",
        )
    ]


def test_revision_merge_rejects_expanded_claim_surface() -> None:
    request = _input()
    source = request.retrieved_chunks[0].source
    original = _fixture_response(request, ResourceType.PRACTICE_GUIDE, [source])
    proposed_content = original.structured_content.model_copy(deep=True)
    assert isinstance(proposed_content, PracticeGuideContent)
    proposed_content.steps[0].expected_result = "第一项新结论。第二项新结论。"

    merged = _merge_revision_candidate(
        original,
        original.model_copy(update={"structured_content": proposed_content}),
        ["steps[0].expected_result[0]"],
    )

    assert (
        merged.structured_content.steps[0].expected_result
        == original.structured_content.steps[0].expected_result
    )


def test_revision_merge_removes_residual_audited_atomic_claim() -> None:
    request = _input()
    source = request.retrieved_chunks[0].source
    original = _fixture_response(request, ResourceType.PRACTICE_GUIDE, [source])
    content = original.structured_content.model_copy(deep=True)
    assert isinstance(content, PracticeGuideContent)
    content.steps[0].expected_result = "保留有证据的结果。删除无依据的固定结论。"
    original = original.model_copy(update={"structured_content": content})

    merged = _merge_revision_candidate(
        original,
        original,
        ["steps[0].expected_result[1]"],
        {
            "steps[0].expected_result[1]": ["删除无依据的固定结论"],
        },
    )

    assert isinstance(merged.structured_content, PracticeGuideContent)
    assert merged.structured_content.steps[0].expected_result == "保留有证据的结果。"


def test_downstream_repair_cannot_restore_audited_instruction_claim() -> None:
    request = _input()
    source = request.retrieved_chunks[0].source
    response = _fixture_response(request, ResourceType.PRACTICE_GUIDE, [source])
    content = response.structured_content.model_copy(deep=True)
    assert isinstance(content, PracticeGuideContent)
    rejected = (
        "仅当状态码为 2xx 且 Content-Type 为 application/json 时，"
        "才尝试解析响应体。"
    )
    content.steps[0].instruction = (
        "响应返回后，先检查 HTTP 状态码与响应头中的 Content-Type；" + rejected
    )
    repaired = response.model_copy(update={"structured_content": content})

    stabilized = _strip_audited_claims_after_repairs(
        repaired,
        ResourceType.PRACTICE_GUIDE,
        {"steps[0].instruction[1]": [rejected]},
    )

    assert isinstance(stabilized.structured_content, PracticeGuideContent)
    assert stabilized.structured_content.steps[0].instruction == (
        "响应返回后，先检查 HTTP 状态码与响应头中的 Content-Type；"
    )


def test_revision_merge_replaces_unchanged_single_claim_with_safe_fallback() -> None:
    request = _input()
    source = request.retrieved_chunks[0].source
    original = _fixture_response(request, ResourceType.PRACTICE_GUIDE, [source])
    content = original.structured_content.model_copy(deep=True)
    assert isinstance(content, PracticeGuideContent)
    rejected = "API 默认 30 秒超时"
    content.environment_requirements[0] = rejected
    original = original.model_copy(update={"structured_content": content})
    paths = ["environment_requirements[0][0]"]
    before = _revision_field_fingerprints(original.structured_content, paths)

    merged = _merge_revision_candidate(
        original,
        original,
        paths,
        {"environment_requirements[0][0]": [rejected]},
    )
    after = _revision_field_fingerprints(merged.structured_content, paths)

    assert isinstance(merged.structured_content, PracticeGuideContent)
    assert merged.structured_content.environment_requirements[0] == (
        "练习前请确认所需材料与受控环境已经准备妥当。"
    )
    assert before != after


def test_deterministic_convergence_removes_atomic_claim_without_model_call() -> None:
    request = _input()
    source = request.retrieved_chunks[0].source
    requirements = request.requirements.model_copy(
        update={
            "required_knowledge_ids": [source.knowledge_id],
            "resource_knowledge_targets": {
                ResourceType.LECTURE: [source.knowledge_id]
            },
            "source_whitelist": [source.source_ref_id],
            "revision_plan": RevisionPlan(
                revision_count=2,
                resource_types=[ResourceType.LECTURE],
                field_paths_by_resource={
                    ResourceType.LECTURE: ["core_concepts[0].explanation[1]"]
                },
                required_changes=["[deterministic_convergence_v1]"],
            )
        }
    )
    request = request.model_copy(
        update={
            "requirements": requirements,
            "retrieved_chunks": [
                chunk
                for chunk in request.retrieved_chunks
                if chunk.source.source_ref_id == source.source_ref_id
            ],
        }
    )
    candidate = _fixture_response(request, ResourceType.LECTURE, [source])
    content = candidate.structured_content.model_copy(deep=True)
    assert isinstance(content, LectureContent)
    removable = "该声明缺少足够证据"
    content.core_concepts[0].explanation = f"保留已有知识说明；{removable}。"
    previous = GeneratedResourceArtifact(
        resource_type=ResourceType.LECTURE,
        structured_content=content,
        review_claims=build_review_claims(ResourceType.LECTURE, content),
        content_md="上一轮候选资源",
        difficulty=candidate.difficulty,
        source_refs=[source],
        knowledge_coverage={source.knowledge_id: [source.source_ref_id]},
    )

    with collect_model_calls() as collector:
        output = ContentGenerationAgent(
            generator=object(), renderer=render_resource_markdown
        ).converge(
            request,
            [previous],
            {
                ResourceType.LECTURE: {
                    "core_concepts[0].explanation[1]": [removable]
                }
            },
        )

    revised = output.resources[0].structured_content
    assert isinstance(revised, LectureContent)
    assert revised.core_concepts[0].explanation == "保留已有知识说明"
    assert collector.snapshot() == []


def test_claim_free_practice_convergence_does_not_inject_source_sentence() -> None:
    request = _input()
    chunk = request.retrieved_chunks[0].model_copy(
        update={
            "content": (
                "操作步骤：发送请求后读取响应状态码和响应体。\n"
                "预期结果：记录实际返回的状态码和响应结构。"
            )
        }
    )
    source = chunk.source
    requirements = request.requirements.model_copy(
        update={
            "resource_types": [ResourceType.PRACTICE_GUIDE],
            "required_knowledge_ids": [source.knowledge_id],
            "resource_knowledge_targets": {
                ResourceType.PRACTICE_GUIDE: [source.knowledge_id]
            },
            "source_whitelist": [source.source_ref_id],
            "revision_plan": RevisionPlan(
                revision_count=2,
                resource_types=[ResourceType.PRACTICE_GUIDE],
                field_paths_by_resource={
                    ResourceType.PRACTICE_GUIDE: ["environment_requirements[0][0]"]
                },
                required_changes=["[deterministic_convergence_v1]"],
            ),
        }
    )
    context = request.context.model_copy(
        update={"resource_types": [ResourceType.PRACTICE_GUIDE]}
    )
    request = request.model_copy(
        update={
            "context": context,
            "requirements": requirements,
            "retrieved_chunks": [chunk],
        }
    )
    candidate = _fixture_response(request, ResourceType.PRACTICE_GUIDE, [source])
    content = candidate.structured_content.model_copy(deep=True)
    assert isinstance(content, PracticeGuideContent)
    content.environment_requirements = ["练习前请确认所需材料与受控环境已经准备妥当。"]
    content.acceptance_criteria = ["完成练习后，提交学习记录并标注核对依据。"]
    content.steps = [
        step.model_copy(
            update={
                "instruction": "发送请求后读取响应状态码和响应体；再整理处理流程。",
                "code_or_command": None,
                "expected_result": "记录实际结果，并与引用材料中的描述进行核对。",
                "troubleshooting": None,
            }
        )
        for step in content.steps
    ]
    previous = GeneratedResourceArtifact(
        resource_type=ResourceType.PRACTICE_GUIDE,
        structured_content=content,
        review_claims=build_review_claims(ResourceType.PRACTICE_GUIDE, content),
        content_md="上一轮候选资源",
        difficulty=candidate.difficulty,
        source_refs=[source],
        knowledge_coverage={source.knowledge_id: [source.source_ref_id]},
    )

    output = ContentGenerationAgent(
        generator=object(), renderer=render_resource_markdown
    ).converge(request, [previous], {})

    revised = output.resources[0].structured_content
    assert isinstance(revised, PracticeGuideContent)
    assert revised.steps[0].instruction == "发送请求后读取响应状态码和响应体；再整理处理流程。"
    assert revised.environment_requirements == content.environment_requirements
    assert revised.acceptance_criteria == content.acceptance_criteria
    assert revised.steps[1:] == content.steps[1:]


def test_claim_free_practice_revision_preserves_structured_claims_for_review() -> None:
    request = _input()
    chunk = request.retrieved_chunks[0].model_copy(
        update={"content": "概念说明：比较不同材料中的定义、范围与关系。"}
    )
    source = chunk.source
    requirements = request.requirements.model_copy(
        update={
            "resource_types": [ResourceType.PRACTICE_GUIDE],
            "required_knowledge_ids": [source.knowledge_id],
            "resource_knowledge_targets": {
                ResourceType.PRACTICE_GUIDE: [source.knowledge_id]
            },
            "source_whitelist": [source.source_ref_id],
            "revision_plan": RevisionPlan(
                revision_count=2,
                resource_types=[ResourceType.PRACTICE_GUIDE],
                field_paths_by_resource={
                    ResourceType.PRACTICE_GUIDE: ["environment_requirements[0][0]"]
                },
                required_changes=["[deterministic_convergence_v1]"],
            ),
        }
    )
    context = request.context.model_copy(
        update={"resource_types": [ResourceType.PRACTICE_GUIDE]}
    )
    request = request.model_copy(
        update={
            "context": context,
            "requirements": requirements,
            "retrieved_chunks": [chunk],
        }
    )
    candidate = _fixture_response(request, ResourceType.PRACTICE_GUIDE, [source])
    content = candidate.structured_content.model_copy(deep=True)
    assert isinstance(content, PracticeGuideContent)
    content.environment_requirements = ["练习前请确认所需材料与受控环境已经准备妥当。"]
    content.acceptance_criteria = ["完成练习后，提交学习记录并标注核对依据。"]
    content.steps = [
        step.model_copy(
            update={
                "instruction": "不同材料中的定义、范围与关系可能存在差异；请比较并分析。",
                "code_or_command": None,
                "expected_result": "记录实际结果，并与引用材料中的描述进行核对。",
                "troubleshooting": None,
            }
        )
        for step in content.steps
    ]
    previous = GeneratedResourceArtifact(
        resource_type=ResourceType.PRACTICE_GUIDE,
        structured_content=content,
        review_claims=build_review_claims(ResourceType.PRACTICE_GUIDE, content),
        content_md="上一轮候选资源",
        difficulty=candidate.difficulty,
        source_refs=[source],
        knowledge_coverage={source.knowledge_id: [source.source_ref_id]},
    )

    output = ContentGenerationAgent(
        generator=object(), renderer=render_resource_markdown
    ).converge(request, [previous], {})

    claims = output.resources[0].review_claims
    assert any(claim.field_path.startswith("steps[0].instruction") for claim in claims)
    assert not any(claim.field_path.startswith("steps[0].expected_result") for claim in claims)


def test_generation_agent_accepts_pedagogical_revision_without_field_capability() -> None:
    request = _input()
    source = request.retrieved_chunks[0].source
    target_ids = [source.knowledge_id]
    requirements = request.requirements.model_copy(
        update={
            "resource_types": [ResourceType.PRACTICE_GUIDE],
            "required_knowledge_ids": target_ids,
            "resource_knowledge_targets": {ResourceType.PRACTICE_GUIDE: target_ids},
            "revision_plan": RevisionPlan(
                revision_count=1,
                resource_types=[ResourceType.PRACTICE_GUIDE],
                field_paths_by_resource={
                    ResourceType.PRACTICE_GUIDE: ["steps[0].expected_result[0]"]
                },
            ),
        }
    )
    context = request.context.model_copy(
        update={"resource_types": [ResourceType.PRACTICE_GUIDE]}
    )
    request = request.model_copy(update={"context": context, "requirements": requirements})
    candidate = _fixture_response(request, ResourceType.PRACTICE_GUIDE, [source])
    previous = GeneratedResourceArtifact(
        resource_type=ResourceType.PRACTICE_GUIDE,
        structured_content=candidate.structured_content,
        review_claims=build_review_claims(
            ResourceType.PRACTICE_GUIDE, candidate.structured_content
        ),
        content_md="上一轮候选资源",
        difficulty=candidate.difficulty,
        source_refs=[source],
        knowledge_coverage={source.knowledge_id: [source.source_ref_id]},
    )
    generator = CandidateRevisionGenerator()

    output = ContentGenerationAgent(
        generator=generator, renderer=render_resource_markdown
    ).revise(request, [previous])

    assert generator.revise_calls == 1
    revised = output.resources[0].structured_content
    assert isinstance(revised, PracticeGuideContent)
    assert revised.steps[0].expected_result == "记录实际结果并与引用材料核对。"


def test_revision_structure_failure_replaces_rejected_practice_field() -> None:
    request = _input()
    source = request.retrieved_chunks[0].source
    target_ids = [source.knowledge_id]
    requirements = request.requirements.model_copy(
        update={
            "resource_types": [ResourceType.PRACTICE_GUIDE],
            "required_knowledge_ids": target_ids,
            "resource_knowledge_targets": {ResourceType.PRACTICE_GUIDE: target_ids},
            "revision_plan": RevisionPlan(
                revision_count=1,
                resource_types=[ResourceType.PRACTICE_GUIDE],
                field_paths_by_resource={
                    ResourceType.PRACTICE_GUIDE: ["steps[0].expected_result[0]"]
                },
            ),
        }
    )
    context = request.context.model_copy(
        update={"requested_resource_types": [ResourceType.PRACTICE_GUIDE]}
    )
    request = request.model_copy(update={"context": context, "requirements": requirements})
    candidate = _fixture_response(request, ResourceType.PRACTICE_GUIDE, [source])
    content = candidate.structured_content.model_copy(deep=True)
    assert isinstance(content, PracticeGuideContent)
    rejected_claim = content.steps[0].expected_result
    previous = GeneratedResourceArtifact(
        resource_type=ResourceType.PRACTICE_GUIDE,
        structured_content=content,
        review_claims=build_review_claims(ResourceType.PRACTICE_GUIDE, content),
        content_md="上一轮候选资源",
        difficulty=candidate.difficulty,
        source_refs=[source],
        knowledge_coverage={source.knowledge_id: [source.source_ref_id]},
    )
    generator = InvalidCandidateRevisionGenerator()

    with collect_model_calls() as collector:
        output = ContentGenerationAgent(
            generator=generator, renderer=render_resource_markdown
        ).revise(
            request,
            [previous],
            {
                ResourceType.PRACTICE_GUIDE: {
                    "steps[0].expected_result[0]": [rejected_claim]
                }
            },
        )

    assert generator.revise_calls == 1
    revised = output.resources[0].structured_content
    assert isinstance(revised, PracticeGuideContent)
    assert rejected_claim != revised.steps[0].expected_result
    assert revised.steps[0].expected_result == "形成与本步骤相关的学习检查表，列出关键观察项和核对结论。"
    assert not _content_policy_violations(revised)
    assert collector.snapshot()[0]["correction_kind"] == (
        "field_revision_structure_fallback"
    )
    assert collector.snapshot()[0]["validation_fields"] == [
        "structured_content.steps.0.expected_result"
    ]




def test_v3_generation_fixture_supports_all_resource_types() -> None:
    request = _input()
    request = request.model_copy(
        update={
            "retrieved_chunks": [
                chunk.model_copy(
                    update={
                        "content": (
                            f"{chunk.content}\n\n## 应用任务\n"
                            "读取检索结果并按知识点标识核对来源。\n\n"
                            "## 预期结果\n形成包含知识点标识和来源标识的核对记录。"
                        )
                    }
                )
                for chunk in request.retrieved_chunks
            ]
        }
    )
    resource_types = list(ResourceType)
    context = request.context.model_copy(update={"resource_types": resource_types})
    requirements = GenerationRequirements(
        resource_types=resource_types,
        target_difficulty=request.requirements.target_difficulty,
        strategy=request.requirements.strategy,
        required_knowledge_ids=request.requirements.required_knowledge_ids,
        source_whitelist=request.requirements.source_whitelist,
    )
    expanded = _with_formal_question_bank(
        request.model_copy(update={"context": context, "requirements": requirements})
    )

    output = ContentGenerationAgent(renderer=render_resource_markdown).execute(expanded)

    assert {resource.resource_type for resource in output.resources} == set(ResourceType)
    assert all(resource.content_md for resource in output.resources)


def test_v3_generation_reports_missing_coverage_without_model_repair(caplog) -> None:
    request = _input()
    original = request.retrieved_chunks[0]
    second = original.model_copy(
        update={
            "chunk_id": "AIAPP-K030::chunk::0",
            "knowledge_id": "AIAPP-K030",
            "source": original.source.model_copy(
                update={
                    "source_ref_id": "AIAPP-K030::chunk::0",
                    "knowledge_id": "AIAPP-K030",
                }
            ),
        }
    )
    requirements = request.requirements.model_copy(
        update={
            "required_knowledge_ids": ["AIAPP-K029", "AIAPP-K030"],
            "resource_knowledge_targets": {ResourceType.LECTURE: ["AIAPP-K029", "AIAPP-K030"]},
            "source_whitelist": [
                original.source.source_ref_id,
                second.source.source_ref_id,
            ],
        }
    )
    expanded = request.model_copy(
        update={"retrieved_chunks": [original, second], "requirements": requirements}
    )
    generator = CoverageRepairGenerator()

    output = ContentGenerationAgent(generator=generator, renderer=render_resource_markdown).execute(
        expanded
    )

    assert generator.repair_calls == 0
    assert set(output.resources[0].knowledge_coverage) == {"AIAPP-K029"}
    assert len(output.resources[0].structured_content.core_concepts) == 1
    assert "generated_coverage_incomplete" in caplog.text


def test_v3_generation_module_has_no_legacy_dependency() -> None:
    imported = __import__("app.agents.generation_agent", fromlist=["*"])
    source = __import__("inspect").getsource(imported)
    assert "legacy_contracts" not in source
    assert "legacy_state" not in source


def test_generation_payload_uses_a_resource_specific_schema() -> None:
    request = _input()
    sources = [chunk.source for chunk in request.retrieved_chunks]
    lecture_payload = _generation_payload(request, ResourceType.LECTURE, sources)
    lecture_schema = lecture_payload["output_schema"]
    quiz_request = request.model_copy(
        update={
            "requirements": request.requirements.model_copy(
                update={
                    "resource_types": [ResourceType.GRADED_QUIZ],
                    "resource_knowledge_targets": {
                        ResourceType.GRADED_QUIZ: request.requirements.required_knowledge_ids
                    },
                }
            )
        }
    )
    quiz_request = _with_formal_question_bank(quiz_request)
    quiz_schema = _generation_payload(quiz_request, ResourceType.GRADED_QUIZ, sources)[
        "output_schema"
    ]

    assert "GradedQuizContent" not in str(lecture_schema)
    assert "LectureContent" not in str(quiz_schema)
    assert "quiz_blueprint" in _generation_payload(quiz_request, ResourceType.GRADED_QUIZ, sources)
    assert any("summary 只能总结" in rule for rule in lecture_payload["source_reference_rules"])
    assert any(
        "命令、配置、预期结果和排错结论" in rule
        for rule in lecture_payload["source_reference_rules"]
    )


def test_quiz_blueprint_detects_slot_drift() -> None:
    request = _input()
    requirements = request.requirements.model_copy(
        update={
            "resource_types": [ResourceType.GRADED_QUIZ],
            "resource_knowledge_targets": {
                ResourceType.GRADED_QUIZ: request.requirements.required_knowledge_ids
            },
        }
    )
    quiz_request = request.model_copy(update={"requirements": requirements})
    quiz_request = _with_formal_question_bank(quiz_request)
    sources = [chunk.source for chunk in quiz_request.retrieved_chunks]
    response = _fixture_response(quiz_request, ResourceType.GRADED_QUIZ, sources)
    assert isinstance(response.structured_content, GradedQuizContent)
    assert not _quiz_blueprint_violations(
        response.structured_content, _quiz_blueprint(quiz_request, sources)
    )

    questions = list(response.structured_content.questions)
    questions[0] = questions[0].model_copy(update={"knowledge_id": "wrong-knowledge"})
    invalid = response.structured_content.model_copy(update={"questions": questions})
    violations = _quiz_blueprint_violations(invalid, _quiz_blueprint(quiz_request, sources))
    assert {item["field"] for item in violations} == {"knowledge_id"}


def test_quiz_blueprint_uses_certified_attribution_not_runtime_token_overlap() -> None:
    request = _input()
    requirements = request.requirements.model_copy(
        update={
            "resource_types": [ResourceType.GRADED_QUIZ],
            "resource_knowledge_targets": {
                ResourceType.GRADED_QUIZ: request.requirements.required_knowledge_ids
            },
        }
    )
    quiz_request = _with_formal_question_bank(
        request.model_copy(update={"requirements": requirements})
    )
    sources = [chunk.source for chunk in quiz_request.retrieved_chunks]
    blueprint = _quiz_blueprint(quiz_request, sources)
    content = _fixture_response(
        quiz_request, ResourceType.GRADED_QUIZ, sources
    ).structured_content
    assert isinstance(content, GradedQuizContent)

    # The fixed formal-question identity, primary knowledge and certified
    # evidence stay intact even where wording leans on a related target.
    other_chunk = next(
        chunk
        for chunk in quiz_request.retrieved_chunks
        if chunk.knowledge_id != content.questions[0].knowledge_id
    )
    questions = list(content.questions)
    questions[0] = questions[0].model_copy(
        update={
            "prompt": f"综合比较：{other_chunk.content}",
            "correct_answer": "按已认证题目的答案评分。",
            "explanation": "该题的主归因、真实关联和来源已在题目认证时验证。",
        }
    )
    integrated = content.model_copy(update={"questions": questions})

    assert not _quiz_blueprint_violations(integrated, blueprint, quiz_request)


def test_failed_structured_generation_is_collected_without_model_content() -> None:
    with collect_model_calls() as collector:
        with pytest.raises(GenerationError, match="generated_structured_output_invalid"):
            ContentGenerationAgent(
                generator=InvalidStructuredOutputGenerator(),
                renderer=render_resource_markdown,
            ).execute(_input())

    assert collector.snapshot() == [
        {
            "provider_mode": "live",
            "model_name": "test-model",
            "tokens_input": 120,
            "tokens_output": 80,
            "duration_ms": 10,
            "role": "generation_model",
            "resource_type": "unknown",
            "status": "failed",
            "attempt_count": 2,
            "validation_fields": ["structured_content.questions.5.options"],
        }
    ]


def test_local_structure_failure_reports_precise_field_paths() -> None:
    with pytest.raises(
        GenerationError,
        match="generated_structure_validation_failed",
    ) as captured:
        ContentGenerationAgent(
            generator=InvalidLocalStructureGenerator(),
            renderer=render_resource_markdown,
        ).execute(_input())

    assert captured.value.field_paths == ["structured_content"]


def test_quiz_is_assembled_from_formal_question_bank_without_model_repair() -> None:
    request = _input()
    requirements = request.requirements.model_copy(
        update={
            "resource_types": [ResourceType.GRADED_QUIZ],
            "resource_knowledge_targets": {
                ResourceType.GRADED_QUIZ: request.requirements.required_knowledge_ids
            },
        }
    )
    repair_generator = QuizGeneratorMustNotRun()
    context = request.context.model_copy(update={"resource_types": [ResourceType.GRADED_QUIZ]})
    bank_request = _with_formal_question_bank(
        request.model_copy(update={"context": context, "requirements": requirements})
    )
    output = ContentGenerationAgent(
        generator=repair_generator, renderer=render_resource_markdown
    ).execute(bank_request)

    quiz = output.resources[0].structured_content
    assert isinstance(quiz, GradedQuizContent)
    assert len(quiz.questions) == 3
    assert all(question.question_id.startswith("formal_") for question in quiz.questions)
    assert all(question.reference_question_ids == [question.question_id] for question in quiz.questions)
