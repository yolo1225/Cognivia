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
    ResourceType,
    RevisionPlan,
)
from app.agents.generation_agent import (
    GeneratedContentResponse,
    ContentGenerationAgent,
    GenerationError,
    RevisionFieldPatch,
    RevisionPatchResponse,
    _apply_quiz_blueprint_fallback,
    _apply_revision_patches,
    _audited_quiz_slot_violations,
    _sanitize_revision_patches,
    _stabilize_lecture_summary,
    _generation_payload,
    _quiz_blueprint,
    _quiz_blueprint_violations,
    _fixture_response,
    _ground_practice_revision_fallbacks,
    _apply_content_policy_fallback,
    _apply_practice_evidence_fallback,
    _content_policy_violations,
    _evidence_depth_violations,
    _merge_coverage_additions,
    _merge_revision_candidate,
    _normalize_revision_path,
    _revision_field_fingerprints,
    _strip_audited_claims_after_repairs,
)
from app.agents.observability import collect_model_calls
from app.agents.domain_evidence_policy import (
    EvidenceCapability,
    get_domain_evidence_policy,
    normalize_evidence_capabilities,
)
from app.services.llm_service import ModelResponseError


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


class InvalidLocalStructureGenerator:
    def generate(self, _request, _resource_type, _allowed_sources):
        return {"difficulty": 2}


class QuizSlotRepairGenerator:
    repair_calls = 0

    def generate(self, request, resource_type, allowed_sources):
        response = _fixture_response(request, resource_type, allowed_sources)
        if resource_type != ResourceType.GRADED_QUIZ:
            return response
        content = response.structured_content.model_copy(deep=True)
        assert isinstance(content, GradedQuizContent)
        questions = list(content.questions)
        questions[0] = questions[0].model_copy(update={"knowledge_id": "wrong-knowledge"})
        return response.model_copy(
            update={"structured_content": content.model_copy(update={"questions": questions})}
        )

    def repair_quiz(self, request, allowed_sources, _candidate, _violations):
        self.repair_calls += 1
        return _fixture_response(request, ResourceType.GRADED_QUIZ, allowed_sources)


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


def test_v3_generation_emits_contract_artifact_and_deterministic_markdown() -> None:
    output = ContentGenerationAgent(
        generator=StubGenerator(), renderer=render_resource_markdown
    ).execute(_input())

    assert output.contract_version == "agent-contract-v6"
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


def test_v3_generation_rejects_sources_outside_whitelist() -> None:
    with pytest.raises(GenerationError, match="generated_source_outside_whitelist"):
        ContentGenerationAgent(
            generator=ForeignSourceGenerator(), renderer=render_resource_markdown
        ).execute(_input())


def test_generation_repairs_forbidden_source_meta_claim_once() -> None:
    generator = ContentPolicyRepairGenerator()
    output = ContentGenerationAgent(generator=generator, renderer=render_resource_markdown).execute(
        _input()
    )

    assert generator.repair_calls == 1
    content = output.resources[0].structured_content
    assert content.summary == _input().retrieved_chunks[0].content
    assert not _content_policy_violations(content)


def test_generation_downgrades_unrepaired_source_meta_claim() -> None:
    generator = UnrepairedContentPolicyGenerator()
    output = ContentGenerationAgent(
        generator=generator, renderer=render_resource_markdown
    ).execute(_input())

    assert generator.repair_calls == 1
    content = output.resources[0].structured_content
    assert isinstance(content, LectureContent)
    assert content.summary == "请结合本讲义的核心概念，梳理关键要点并记录自己的理解。"
    assert not _content_policy_violations(content)


def test_content_policy_fallback_keeps_valid_text_around_provenance_claim() -> None:
    request = _input()
    response = _fixture_response(request, ResourceType.LECTURE, [request.retrieved_chunks[0].source])
    content = response.structured_content.model_copy(deep=True)
    assert isinstance(content, LectureContent)
    content.summary = "RAG 将检索结果作为生成上下文。所有结论均源自所列官方文档。"

    sanitized = _apply_content_policy_fallback(
        content,
        [{"path": "summary", "code": "forbidden_meta_claim"}],
    )

    assert isinstance(sanitized, LectureContent)
    assert sanitized.summary == "RAG 将检索结果作为生成上下文"
    assert not _content_policy_violations(sanitized)


def test_unified_policy_removes_misplaced_expected_result_action() -> None:
    request = _input()
    response = _fixture_response(
        request,
        ResourceType.PRACTICE_GUIDE,
        [request.retrieved_chunks[0].source],
    )
    content = response.structured_content.model_copy(deep=True)
    assert isinstance(content, PracticeGuideContent)
    content.steps[0].expected_result = "处理完成后返回任务标识。请记录实际观察结果。"

    violations = _content_policy_violations(content)
    once = _apply_content_policy_fallback(content, violations)
    twice = _apply_content_policy_fallback(once, _content_policy_violations(once))

    assert any(
        item == {
            "path": "steps[0].expected_result",
            "code": "misplaced_field_content",
        }
        for item in violations
    )
    assert isinstance(once, PracticeGuideContent)
    assert once.steps[0].expected_result == "处理完成后返回任务标识"
    assert twice == once
    assert not _content_policy_violations(once)


def test_content_policy_replaces_sole_implementation_meta_claim_safely() -> None:
    request = _input()
    response = _fixture_response(
        request,
        ResourceType.PRACTICE_GUIDE,
        [request.retrieved_chunks[0].source],
    )
    content = response.structured_content.model_copy(deep=True)
    assert isinstance(content, PracticeGuideContent)
    content.steps[0].expected_result = "标注由代码落实的安全与校验项。"

    sanitized = _apply_content_policy_fallback(
        content,
        _content_policy_violations(content),
    )

    assert isinstance(sanitized, PracticeGuideContent)
    assert sanitized.steps[0].expected_result == (
        "记录实际结果，并与引用材料中的描述进行核对。"
    )
    assert not _content_policy_violations(sanitized)


def test_content_policy_removes_directive_misplaced_in_expected_result() -> None:
    request = _input()
    response = _fixture_response(
        request,
        ResourceType.PRACTICE_GUIDE,
        [request.retrieved_chunks[0].source],
    )
    content = response.structured_content.model_copy(deep=True)
    assert isinstance(content, PracticeGuideContent)
    content.steps[0].expected_result = (
        "校验通过表示响应符合当前契约；"
        "校验失败时应暴露具体缺失或类型不符的字段，而非忽略或强转；"
        "检查记录包含实际响应与契约的差异。"
    )

    violations = _content_policy_violations(content)
    sanitized = _apply_content_policy_fallback(content, violations)

    assert any(
        item == {
            "path": "steps[0].expected_result",
            "code": "misplaced_field_content",
        }
        for item in violations
    )
    assert isinstance(sanitized, PracticeGuideContent)
    assert sanitized.steps[0].expected_result == "校验通过表示响应符合当前契约"
    assert not _content_policy_violations(sanitized)


def test_lecture_summary_drops_facts_not_taught_by_core_concepts() -> None:
    request = _input()
    response = _fixture_response(
        request, ResourceType.LECTURE, [request.retrieved_chunks[0].source]
    )
    content = response.structured_content.model_copy(deep=True)
    assert isinstance(content, LectureContent)
    content.core_concepts[0].explanation = "API 调用前应限制输入大小。"
    content.summary = "API 调用前应限制输入大小。调用后需校验未讲授的固定响应字段。"

    stabilized = _stabilize_lecture_summary(content)

    assert stabilized.summary == "API 调用前应限制输入大小。"


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
    sources = [chunk.source for chunk in request.retrieved_chunks]
    content = _fixture_response(request, ResourceType.GRADED_QUIZ, sources).structured_content
    content = content.model_copy(deep=True)
    content.questions[0].prompt = "请依据 AIAPP-K029::chunk::0 作答。"
    content.questions[0].correct_answer = "答案来自 AIAPP-K029::chunk::0。"
    content.questions[0].explanation = "AIAPP-K029::chunk::0 明确支持该答案。"

    violations = _content_policy_violations(content)
    sanitized = _apply_content_policy_fallback(content, violations)

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
    sources = [chunk.source for chunk in request.retrieved_chunks]
    content = _fixture_response(request, ResourceType.GRADED_QUIZ, sources).structured_content
    content = content.model_copy(deep=True)
    content.questions[0].explanation = (
        "HTTP 请求包含方法和目标 URI；RFC 未声明响应头字段可选；因此仅选前两项。"
    )

    violations = _content_policy_violations(content)
    sanitized = _apply_content_policy_fallback(content, violations)

    assert any(item["code"] == "unsupported_distractor_rationale" for item in violations)
    assert sanitized.questions[0].explanation == "HTTP 请求包含方法和目标 URI；"


def test_generation_deterministically_downgrades_unsupported_practice_fields() -> None:
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
    generator = UnrepairedPracticeEvidenceGenerator()

    output = ContentGenerationAgent(
        generator=generator, renderer=render_resource_markdown
    ).execute(request.model_copy(update={"context": context, "requirements": requirements}))

    content = output.resources[0].structured_content
    assert isinstance(content, PracticeGuideContent)
    assert generator.repair_calls == 1
    assert content.environment_requirements == ["准备练习所需的材料与受控环境。"]
    assert content.steps[0].instruction == "阅读并梳理引用材料中明确描述的处理流程。"
    assert content.steps[0].expected_result == "记录实际结果并与引用材料中的描述进行核对。"
    assert content.steps[0].code_or_command is None
    assert content.steps[0].troubleshooting is None
    assert content.acceptance_criteria[0] == "形成学习记录并标注所依据的材料。"
    assert content.steps[0].source_ref_ids
    assert not _evidence_depth_violations(
        content, request.model_copy(update={"context": context, "requirements": requirements}),
        [request.retrieved_chunks[0].source],
    )


def test_concept_evidence_cannot_support_executable_practice_code() -> None:
    request = _input()
    source = request.retrieved_chunks[0].source
    response = _fixture_response(request, ResourceType.PRACTICE_GUIDE, [source])
    content = response.structured_content.model_copy(deep=True)
    content.environment_requirements[0] = "安装并配置指定版本的 Python 环境"
    content.steps[0].instruction = "执行 Git 提交并调用 HTTP 接口"
    content.steps[0].code_or_command = "python app.py"
    content.steps[0].expected_result = "接口固定返回成功状态"

    violations = _evidence_depth_violations(content, request, [source])

    assert {
        "path": "steps[0].code_or_command",
        "code": "executable_evidence_missing",
    } in violations
    assert {
        "path": "steps[0].instruction",
        "code": "operation_evidence_missing",
    } in violations
    assert {
        "path": "steps[0].expected_result",
        "code": "expected_result_evidence_missing",
    } in violations
    assert any(item["code"] == "environment_evidence_missing" for item in violations)


def test_practice_fallback_separates_git_commands_glued_by_revision() -> None:
    request = _input()
    source = request.retrieved_chunks[0].source
    response = _fixture_response(request, ResourceType.PRACTICE_GUIDE, [source])
    content = response.structured_content.model_copy(deep=True)
    content.steps[0].code_or_command = 'git diffgit commit -m "describe intent"'

    sanitized = _apply_practice_evidence_fallback(content, [])

    assert sanitized.steps[0].code_or_command == 'git diff\ngit commit -m "describe intent"'


def test_direct_code_evidence_allows_practice_code() -> None:
    request = _input()
    chunk = request.retrieved_chunks[0].model_copy(
        update={"content": "代码示例：```python\nimport json\n```"}
    )
    request = request.model_copy(update={"retrieved_chunks": [chunk]})
    source = chunk.source
    response = _fixture_response(request, ResourceType.PRACTICE_GUIDE, [source])
    content = response.structured_content.model_copy(deep=True)
    content.steps[0].code_or_command = "import json"

    violations = _evidence_depth_violations(content, request, [source])

    assert not any(item["code"] == "executable_evidence_missing" for item in violations)


def test_operation_and_expected_result_evidence_supports_practice_steps() -> None:
    request = _input()
    chunk = request.retrieved_chunks[0].model_copy(
        update={
            "content": (
                "操作步骤：执行受控验证。代码示例：```python\nimport json\n```。"
                "预期结果：完成后输出验证记录。"
            )
        }
    )
    request = request.model_copy(update={"retrieved_chunks": [chunk]})
    source = chunk.source
    response = _fixture_response(request, ResourceType.PRACTICE_GUIDE, [source])

    violations = _evidence_depth_violations(
        response.structured_content, request, [source]
    )

    assert not any(
        item["code"]
        in {
            "environment_evidence_missing",
            "operation_evidence_missing",
            "executable_evidence_missing",
            "expected_result_evidence_missing",
        }
        for item in violations
    )


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


def test_practice_provenance_fallback_covers_every_step_and_is_idempotent() -> None:
    request = _input()
    source = request.retrieved_chunks[0].source
    response = _fixture_response(request, ResourceType.PRACTICE_GUIDE, [source])
    content = response.structured_content.model_copy(deep=True)
    assert isinstance(content, PracticeGuideContent)
    second = content.steps[0].model_copy(
        update={
            "order": 2,
            "instruction": "比较两个方案。所有结论均源自所列官方文档。",
        }
    )
    content.steps.append(second)

    violations = _content_policy_violations(content)
    once = _apply_content_policy_fallback(content, violations)
    twice = _apply_content_policy_fallback(once, _content_policy_violations(once))

    assert isinstance(once, PracticeGuideContent)
    assert once.steps[1].instruction == "比较两个方案"
    assert not _content_policy_violations(once)
    assert twice == once


def test_unrepaired_second_practice_step_converges_without_task_failure() -> None:
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

    content = output.resources[0].structured_content
    assert isinstance(content, PracticeGuideContent)
    assert generator.repair_calls == 1
    assert content.steps[1].instruction == "整理差异"
    assert not _content_policy_violations(content)


def test_explicit_cross_domain_capabilities_override_unstructured_prose() -> None:
    request = _input()
    chunk = request.retrieved_chunks[0].model_copy(
        update={"knowledge_id": "marine_valve", "content": "Calibrate the valve against the reference card."}
    )
    request = request.model_copy(update={"retrieved_chunks": [chunk]})
    source = chunk.source.model_copy(update={"knowledge_id": "marine_valve"})
    response = _fixture_response(request, ResourceType.PRACTICE_GUIDE, [source])
    content = response.structured_content.model_copy(deep=True)
    assert isinstance(content, PracticeGuideContent)
    content.steps[0].instruction = "执行阀门校准。"
    content.steps[0].code_or_command = "CALIBRATE VALVE A"
    content.steps[0].expected_result = "显示校准完成状态。"
    content.steps[0].troubleshooting = "失败时检查阀门位置。"
    declared = {
        "marine_valve": [
            "operation",
            "command",
            "expected_result",
            "error_handling",
        ]
    }

    assert not _evidence_depth_violations(content, request, [source], declared)


def test_declared_concept_capability_cannot_be_promoted_by_body_keywords() -> None:
    request = _input()
    chunk = request.retrieved_chunks[0].model_copy(
        update={"content": "操作步骤：执行命令。预期结果：返回成功状态。"}
    )
    request = request.model_copy(update={"retrieved_chunks": [chunk]})
    source = chunk.source
    content = _fixture_response(
        request, ResourceType.PRACTICE_GUIDE, [source]
    ).structured_content.model_copy(deep=True)
    assert isinstance(content, PracticeGuideContent)
    content.steps[0].instruction = "执行命令并提交请求。"

    violations = _evidence_depth_violations(
        content,
        request,
        [source],
        {chunk.knowledge_id: ["concept"]},
    )

    assert any(item["code"] == "operation_evidence_missing" for item in violations)


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

def test_quiz_blueprint_rejects_revision_placeholders_and_unrelated_answers() -> None:
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
    allowed_sources = [chunk.source for chunk in request.retrieved_chunks]
    response = _fixture_response(request, ResourceType.GRADED_QUIZ, allowed_sources)
    content = response.structured_content.model_copy(deep=True)
    content.questions[0].prompt = "请根据引用材料完成该题并核对答案。"
    content.questions[0].correct_answer = "与所有选项无关的答案"

    violations = _quiz_blueprint_violations(
        content,
        _quiz_blueprint(request, allowed_sources),
    )

    assert {item["field"] for item in violations if item["question_id"] == "Q1"} >= {
        "assessment_content",
        "correct_answer",
    }


def test_audited_quiz_claim_rebuilds_the_entire_question_from_evidence() -> None:
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
    sources = [chunk.source for chunk in request.retrieved_chunks]
    content = _fixture_response(
        request, ResourceType.GRADED_QUIZ, sources
    ).structured_content
    content = content.model_copy(deep=True)
    content.questions[0].correct_answer = "材料未说明的额外因果结论"

    violations = _audited_quiz_slot_violations(
        content,
        {"questions[0].correct_answer": ["材料未说明的额外因果结论"]},
    )
    rebuilt = _apply_quiz_blueprint_fallback(
        content,
        violations,
        _quiz_blueprint(request, sources),
        request,
    )

    assert violations == [{"question_id": "Q1", "field": "assessment_content"}]
    assert rebuilt.questions[0].correct_answer != "材料未说明的额外因果结论"
    assert not _quiz_blueprint_violations(
        rebuilt,
        _quiz_blueprint(request, sources),
        request,
    )


def test_quiz_blueprint_rejects_cross_target_content_and_falls_back_to_target_evidence() -> None:
    request = _input()
    first_chunk = request.retrieved_chunks[0]
    first_body = first_chunk.content
    first_chunk = first_chunk.model_copy(
        update={
            "content": (
                "知识点：不应成为题目答案的元数据\n"
                "分类：测试分类\n"
                "难度：3\n"
                "标签：测试\n"
                "标题：测试标题\n\n"
                f"{first_body}"
            )
        }
    )
    request = request.model_copy(
        update={"retrieved_chunks": [first_chunk, *request.retrieved_chunks[1:]]}
    )
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
    sources = [chunk.source for chunk in request.retrieved_chunks]
    blueprint = _quiz_blueprint(request, sources)
    content = _fixture_response(request, ResourceType.GRADED_QUIZ, sources).structured_content
    content = content.model_copy(deep=True)
    content.questions[0].prompt = "文本向量如何用于语义相似度召回？"
    content.questions[0].correct_answer = "文本向量映射语义"
    content.questions[0].explanation = request.retrieved_chunks[1].content

    violations = _quiz_blueprint_violations(content, blueprint, request)
    fallback = _apply_quiz_blueprint_fallback(content, violations, blueprint, request)

    assert any(
        item["question_id"] == "Q1" and item["field"] == "knowledge_alignment"
        for item in violations
    )
    assert fallback.questions[0].knowledge_id == blueprint[0]["knowledge_id"]
    assert first_body.split("。", 1)[0] in fallback.questions[0].explanation
    assert "不应成为题目答案的元数据" not in fallback.questions[0].correct_answer
    assert "测试分类" not in fallback.questions[0].explanation
    assert not _quiz_blueprint_violations(fallback, blueprint, request)


def test_environment_fact_without_operation_evidence_is_rewritten_as_preparation() -> None:
    request = _input()
    chunk = request.retrieved_chunks[0].model_copy(
        update={"content": "概念说明：输入案例可用于比较学习材料。"}
    )
    request = request.model_copy(update={"retrieved_chunks": [chunk]})
    source = chunk.source
    response = _fixture_response(request, ResourceType.PRACTICE_GUIDE, [source])
    content = response.structured_content.model_copy(deep=True)
    content.environment_requirements[0] = "支持对同一组输入案例反复测试不同提示词变体"

    violations = _evidence_depth_violations(content, request, [source])
    sanitized = _apply_practice_evidence_fallback(content, violations)

    assert {
        "path": "environment_requirements[0]",
        "code": "environment_evidence_missing",
    } in violations
    assert sanitized.environment_requirements[0] == "准备练习所需的材料与受控环境。"
    assert not any(
        item["code"] == "environment_evidence_missing"
        for item in _evidence_depth_violations(sanitized, request, [source])
    )


def test_practice_revision_reuses_cleaned_baseline_for_nonfactual_containers() -> None:
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
    assert content.environment_requirements[0] == "练习前请确认所需材料与受控环境已经准备妥当。"
    assert content.steps[0].expected_result == "记录实际结果，并与引用材料中的描述进行核对。"


def test_practice_revision_cannot_replace_rejected_instruction_with_equivalent_claim() -> None:
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
        "阅读引用材料，整理其中明确描述的处理流程。"
    )


def test_practice_revision_claim_free_instruction_is_grounded_in_cited_evidence() -> None:
    request = _input()
    source = request.retrieved_chunks[0].source
    response = _fixture_response(request, ResourceType.PRACTICE_GUIDE, [source])
    content = response.structured_content.model_copy(deep=True)
    assert isinstance(content, PracticeGuideContent)
    content.steps[0].instruction = "阅读引用材料，整理其中明确描述的处理流程。"

    grounded = _ground_practice_revision_fallbacks(
        response.model_copy(update={"structured_content": content}), request
    )

    assert isinstance(grounded.structured_content, PracticeGuideContent)
    assert grounded.structured_content.steps[0].instruction != content.steps[0].instruction
    assert request.retrieved_chunks[0].content in grounded.structured_content.steps[0].instruction


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


def test_generation_agent_revises_previous_candidate_instead_of_regenerating() -> None:
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
        content_md="上一轮候选资源",
        difficulty=candidate.difficulty,
        source_refs=[source],
        knowledge_coverage={source.knowledge_id: [source.source_ref_id]},
    )
    generator = CandidateRevisionGenerator()

    output = ContentGenerationAgent(
        generator=generator, renderer=render_resource_markdown
    ).revise(request, [previous])

    revised = output.resources[0]
    assert generator.revise_calls == 1
    assert revised.structured_content.title == previous.structured_content.title
    assert (
        revised.structured_content.steps[0].expected_result
        == "记录实际结果并与引用材料核对。"
    )
    assert revised.difficulty == previous.difficulty


def test_revision_structure_failure_uses_valid_candidate_and_audited_fallback() -> None:
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

    revised = output.resources[0].structured_content
    assert isinstance(revised, PracticeGuideContent)
    assert generator.revise_calls == 1
    assert "记录实际结果" in revised.steps[0].expected_result
    assert "引用材料" in revised.steps[0].expected_result
    assert rejected_claim not in revised.steps[0].expected_result
    assert collector.snapshot()[0]["correction_kind"] == (
        "field_revision_structure_fallback"
    )
    assert collector.snapshot()[0]["validation_fields"] == [
        "structured_content.steps.0.expected_result"
    ]


def test_coverage_merge_only_appends_supported_missing_knowledge() -> None:
    request = _input()
    original_chunk = request.retrieved_chunks[0]
    missing_chunk = original_chunk.model_copy(
        update={
            "chunk_id": "AIAPP-K030::chunk::0",
            "knowledge_id": "AIAPP-K030",
            "source": original_chunk.source.model_copy(
                update={
                    "source_ref_id": "AIAPP-K030::chunk::0",
                    "knowledge_id": "AIAPP-K030",
                }
            ),
        }
    )
    request = request.model_copy(
        update={"retrieved_chunks": [original_chunk, missing_chunk]}
    )
    original = _fixture_response(
        request, ResourceType.LECTURE, [original_chunk.source]
    )
    original_payload = original.structured_content.model_dump(mode="python")
    proposed_content = original.structured_content.model_copy(deep=True)
    assert isinstance(proposed_content, LectureContent)
    proposed_content.title = "不应接受的重写标题"
    proposed_content.summary = "不应接受的重写摘要"
    proposed_content.core_concepts[0].explanation = "不应接受的原章节重写"
    proposed_content.core_concepts.append(
        ConceptBlock(
            title="缺失知识点补充",
            explanation="仅追加有来源支持的缺失知识点内容。",
            source_ref_ids=[missing_chunk.source.source_ref_id],
        )
    )
    proposed = original.model_copy(update={"structured_content": proposed_content})

    merged = _merge_coverage_additions(
        original, proposed, {missing_chunk.knowledge_id}, request
    )

    merged_content = merged.structured_content
    assert isinstance(merged_content, LectureContent)
    assert merged_content.model_dump(mode="python") | {
        "core_concepts": original_payload["core_concepts"]
    } == original_payload
    assert merged_content.core_concepts[0].model_dump(mode="python") == original_payload[
        "core_concepts"
    ][0]
    assert len(merged_content.core_concepts) == 2
    assert merged_content.core_concepts[1].source_ref_ids == [
        missing_chunk.source.source_ref_id
    ]


def test_v3_generation_fixture_supports_all_resource_types() -> None:
    request = _input()
    resource_types = list(ResourceType)
    context = request.context.model_copy(update={"resource_types": resource_types})
    requirements = GenerationRequirements(
        resource_types=resource_types,
        target_difficulty=request.requirements.target_difficulty,
        strategy=request.requirements.strategy,
        required_knowledge_ids=request.requirements.required_knowledge_ids,
        source_whitelist=request.requirements.source_whitelist,
    )
    expanded = request.model_copy(update={"context": context, "requirements": requirements})

    output = ContentGenerationAgent(renderer=render_resource_markdown).execute(expanded)

    assert {resource.resource_type for resource in output.resources} == set(ResourceType)
    assert all(resource.content_md for resource in output.resources)


def test_v3_generation_repairs_missing_coverage_once_and_preserves_existing() -> None:
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

    assert generator.repair_calls == 1
    assert set(output.resources[0].knowledge_coverage) == {"AIAPP-K029", "AIAPP-K030"}
    assert len(output.resources[0].structured_content.core_concepts) == 2


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


def test_quiz_slot_repair_only_replaces_invalid_question() -> None:
    request = _input()
    requirements = request.requirements.model_copy(
        update={
            "resource_types": [ResourceType.GRADED_QUIZ],
            "resource_knowledge_targets": {
                ResourceType.GRADED_QUIZ: request.requirements.required_knowledge_ids
            },
        }
    )
    repair_generator = QuizSlotRepairGenerator()
    context = request.context.model_copy(update={"resource_types": [ResourceType.GRADED_QUIZ]})
    output = ContentGenerationAgent(
        generator=repair_generator, renderer=render_resource_markdown
    ).execute(request.model_copy(update={"context": context, "requirements": requirements}))

    quiz = output.resources[0].structured_content
    assert isinstance(quiz, GradedQuizContent)
    assert repair_generator.repair_calls == 1
    assert [question.question_id for question in quiz.questions] == [
        "Q1",
        "Q2",
        "Q3",
        "Q4",
        "Q5",
        "Q6",
    ]
    assert {question.level.value for question in quiz.questions} == {
        "foundation",
        "improvement",
        "challenge",
    }
