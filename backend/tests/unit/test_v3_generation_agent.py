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
    _generation_payload,
    _quiz_blueprint,
    _quiz_blueprint_violations,
    _fixture_response,
    _apply_content_policy_fallback,
    _content_policy_violations,
    _evidence_depth_violations,
    _merge_coverage_additions,
    _merge_revision_candidate,
    _normalize_revision_path,
    _revision_field_fingerprints,
)
from app.agents.observability import collect_model_calls
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
        assert violations == [{"path": "summary", "code": "provenance_meta_claim"}]
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

    assert output.contract_version == "agent-contract-v5"
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


def test_generation_repairs_provenance_meta_claim_once() -> None:
    generator = ContentPolicyRepairGenerator()
    output = ContentGenerationAgent(generator=generator, renderer=render_resource_markdown).execute(
        _input()
    )

    assert generator.repair_calls == 1
    content = output.resources[0].structured_content
    assert content.summary == "RAG 资源应保留可追溯的来源引用。"
    assert not _content_policy_violations(content)


def test_generation_downgrades_unrepaired_provenance_meta_claim() -> None:
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
        [{"path": "summary", "code": "provenance_meta_claim"}],
    )

    assert isinstance(sanitized, LectureContent)
    assert sanitized.summary == "RAG 将检索结果作为生成上下文"
    assert not _content_policy_violations(sanitized)


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
    assert content.environment_requirements == ["与引用材料相符的受控学习环境"]
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
