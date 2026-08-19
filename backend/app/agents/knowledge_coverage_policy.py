from __future__ import annotations

from app.agents.contracts import ResourceType, RetrievedChunk
from app.agents.domain_evidence_policy import EvidenceCapability, get_domain_evidence_policy


class EvidenceGapError(ValueError):
    """A requested resource has no evidence with the capability it requires."""


PRIMARY_OWNER_PRIORITY = (
    ResourceType.PRACTICE_GUIDE,
    ResourceType.LECTURE,
    ResourceType.GRADED_QUIZ,
)


def primary_owner_by_knowledge(
    required_ids: list[str],
    resource_targets: dict[ResourceType | str, list[str]],
) -> dict[str, ResourceType]:
    """Resolve one teaching owner while allowing quiz assessment overlap."""

    normalized = {
        ResourceType(resource_type): set(values)
        for resource_type, values in resource_targets.items()
    }
    owners: dict[str, ResourceType] = {}
    for knowledge_id in dict.fromkeys(required_ids):
        owner = next(
            (
                resource_type
                for resource_type in PRIMARY_OWNER_PRIORITY
                if knowledge_id in normalized.get(resource_type, set())
            ),
            None,
        )
        if owner is None:
            raise EvidenceGapError("evidence_gap")
        owners[knowledge_id] = owner
    return owners


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
    if resource_types == [ResourceType.PRACTICE_GUIDE]:
        operational = [
            knowledge_id
            for knowledge_id in targets
            if EvidenceCapability.OPERATION
            in capabilities_by_id.get(knowledge_id, set())
        ]
        if operational != targets:
            raise EvidenceGapError("evidence_gap")
        result[ResourceType.PRACTICE_GUIDE] = operational
        return result
    if len(resource_types) == 1:
        result[resource_types[0]] = list(targets)
        return result

    for knowledge_id in targets:
        operational = EvidenceCapability.OPERATION in capabilities_by_id.get(
            knowledge_id, set()
        )
        if operational and ResourceType.PRACTICE_GUIDE in result:
            owner = ResourceType.PRACTICE_GUIDE
        elif ResourceType.LECTURE in result:
            owner = ResourceType.LECTURE
        elif ResourceType.GRADED_QUIZ in result:
            owner = ResourceType.GRADED_QUIZ
        else:
            raise EvidenceGapError("evidence_gap")
        result[owner].append(knowledge_id)

    if ResourceType.GRADED_QUIZ in result:
        result[ResourceType.GRADED_QUIZ] = list(targets[:6])

    if ResourceType.PRACTICE_GUIDE in result and not result[ResourceType.PRACTICE_GUIDE]:
        raise EvidenceGapError("evidence_gap")

    # Lecture may explain an operational target as supporting context, but a
    # practice guide must never inherit a conceptual target merely to stay non-empty.
    for resource_type, values in result.items():
        if not values and targets:
            result[resource_type] = [targets[0]]
    return result
