from app.agents.contracts import ResourceType
from app.agents.contract_examples import initial_generation_flow_example
from app.agents.knowledge_coverage_policy import allocate_resource_knowledge_targets


def test_quiz_owns_all_targets_and_requested_resources_are_non_empty() -> None:
    targets = ["K1", "K2"]
    allocated = allocate_resource_knowledge_targets(
        targets,
        [],
        [ResourceType.LECTURE, ResourceType.PRACTICE_GUIDE, ResourceType.GRADED_QUIZ],
    )
    assert allocated[ResourceType.GRADED_QUIZ] == targets
    assert set().union(*map(set, allocated.values())) == set(targets)
    assert all(allocated.values())


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
    )

    assert allocated[ResourceType.LECTURE] == ["concept"]
    assert allocated[ResourceType.PRACTICE_GUIDE] == ["operation"]
