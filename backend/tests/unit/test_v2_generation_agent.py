from __future__ import annotations

import pytest

from app.agents.contract_adapters import render_resource_markdown
from app.agents.contract_examples import initial_generation_flow_example
from app.agents.contracts import (
    GenerateResourceInput,
    GenerationRequirements,
    LectureContent,
    ResourceType,
)
from app.agents.v2_generation_agent import (
    GeneratedContentResponse,
    V2ContentGenerationAgent,
    V2GenerationError,
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


def _input() -> GenerateResourceInput:
    return initial_generation_flow_example()["generate_resource"]["input"]


def test_v2_generation_emits_contract_artifact_and_deterministic_markdown() -> None:
    output = V2ContentGenerationAgent(
        generator=StubGenerator(), renderer=render_resource_markdown
    ).execute(_input())

    assert output.contract_version == "agent-contract-v2"
    assert output.task_id == _input().task_id
    assert [item.resource_type for item in output.resources] == [ResourceType.LECTURE]
    artifact = output.resources[0]
    assert artifact.content_md == render_resource_markdown(
        artifact.structured_content, artifact.source_refs
    )


def test_v2_generation_rejects_non_contract_input() -> None:
    with pytest.raises(V2GenerationError, match="invalid_generate_input_type"):
        V2ContentGenerationAgent(
            generator=StubGenerator(), renderer=render_resource_markdown
        ).execute({})  # type: ignore[arg-type]


def test_v2_generation_rejects_sources_outside_whitelist() -> None:
    with pytest.raises(V2GenerationError, match="generated_source_outside_whitelist"):
        V2ContentGenerationAgent(
            generator=ForeignSourceGenerator(), renderer=render_resource_markdown
        ).execute(_input())


def test_v2_generation_fixture_supports_all_resource_types() -> None:
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
    expanded = request.model_copy(
        update={"context": context, "requirements": requirements}
    )

    output = V2ContentGenerationAgent(renderer=render_resource_markdown).execute(expanded)

    assert {resource.resource_type for resource in output.resources} == set(ResourceType)
    assert all(resource.content_md for resource in output.resources)


def test_v2_generation_module_has_no_legacy_dependency() -> None:
    imported = __import__("app.agents.v2_generation_agent", fromlist=["*"])
    source = __import__("inspect").getsource(imported)
    assert "legacy_contracts" not in source
    assert "legacy_state" not in source
