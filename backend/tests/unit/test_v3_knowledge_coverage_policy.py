from app.agents.contracts import ResourceType
from app.agents.contract_examples import initial_generation_flow_example
import pytest

from app.agents.knowledge_coverage_policy import (
    EvidenceGapError,
    allocate_resource_knowledge_targets,
    primary_owner_by_knowledge,
)


def test_practice_resource_without_operation_evidence_fails_preflight() -> None:
    targets = ["K1", "K2"]
    with pytest.raises(EvidenceGapError, match="evidence_gap"):
        allocate_resource_knowledge_targets(
            targets,
            [],
            [ResourceType.LECTURE, ResourceType.PRACTICE_GUIDE, ResourceType.GRADED_QUIZ],
            "ai_app_dev",
        )


def test_only_structured_operation_evidence_is_allocated_to_practice() -> None:
    base = initial_generation_flow_example()["retrieve_knowledge"]["output"].chunks[0]
    concept = base.model_copy(
        update={
            "knowledge_id": "concept",
            "content": "介绍 API、实现流程和验证原则，不构成代码示例。",
            "source": base.source.model_copy(update={"knowledge_id": "concept"}),
        }
    )
    operation = base.model_copy(
        update={
            "knowledge_id": "operation",
            "content": "## 操作步骤\n1. 检查以下配置文件。",
            "source": base.source.model_copy(update={"knowledge_id": "operation"}),
        }
    )

    allocated = allocate_resource_knowledge_targets(
        ["concept", "operation"],
        [concept, operation],
        [ResourceType.LECTURE, ResourceType.PRACTICE_GUIDE, ResourceType.GRADED_QUIZ],
        "ai_app_dev",
    )

    assert allocated[ResourceType.LECTURE] == ["concept"]
    assert allocated[ResourceType.PRACTICE_GUIDE] == ["operation"]
    assert primary_owner_by_knowledge(["concept", "operation"], allocated) == {
        "concept": ResourceType.LECTURE,
        "operation": ResourceType.PRACTICE_GUIDE,
    }
