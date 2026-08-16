from __future__ import annotations

from app.agents.contracts import ResourceType, RetrievedChunk
from app.agents.domain_evidence_policy import EvidenceCapability, get_domain_evidence_policy


def allocate_resource_knowledge_targets(
    required_ids: list[str],
    chunks: list[RetrievedChunk],
    resource_types: list[ResourceType],
    domain_code: str = "ai_app_dev",
) -> dict[ResourceType, list[str]]:
    """Allocate task targets by resource responsibility, deterministically."""
    targets = list(dict.fromkeys(required_ids))[:10]
    policy = get_domain_evidence_policy(domain_code)
    capabilities_by_id: dict[str, set[EvidenceCapability]] = {}
    for chunk in chunks:
        capabilities_by_id.setdefault(chunk.knowledge_id, set()).update(policy.classify(chunk))
    result: dict[ResourceType, list[str]] = {item: [] for item in resource_types}
    if len(resource_types) == 1:
        result[resource_types[0]] = list(targets)
        return result

    teaching_types = [
        item
        for item in (ResourceType.LECTURE, ResourceType.PRACTICE_GUIDE)
        if item in result
    ]
    for knowledge_id in targets:
        operational = EvidenceCapability.OPERATION in capabilities_by_id.get(
            knowledge_id, set()
        )
        if operational and ResourceType.PRACTICE_GUIDE in result:
            owner = ResourceType.PRACTICE_GUIDE
        elif ResourceType.LECTURE in result:
            owner = ResourceType.LECTURE
        elif teaching_types:
            owner = teaching_types[0]
        else:
            owner = ResourceType.GRADED_QUIZ
        result[owner].append(knowledge_id)

    if ResourceType.GRADED_QUIZ in result:
        result[ResourceType.GRADED_QUIZ] = list(targets[:6])

    # Every requested resource remains demonstrable without forcing all task
    # targets into every resource. The package union still owns the full scope.
    for resource_type, values in result.items():
        if not values and targets:
            result[resource_type] = [targets[0]]
    return result
