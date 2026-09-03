from app.models import GenerationTask, LearningPath, LearningResource
from app.services.resource_matching_service import decide_resource_matching


def _path() -> LearningPath:
    return LearningPath(
        public_id="path_matching",
        path_json={
            "current_node_id": "unit:current",
            "node_states": {
                "unit:current": {
                    "path_node_id": "unit:current",
                    "status": "current",
                    "knowledge_ids": ["current_knowledge"],
                    "focus_knowledge_ids": ["current_knowledge"],
                },
                "unit:future": {
                    "path_node_id": "unit:future",
                    "status": "locked",
                    "knowledge_ids": ["future_knowledge"],
                },
            },
        },
    )


def test_matching_keeps_resource_and_route_decisions_separate() -> None:
    path = _path()
    package = GenerationTask(
        resource_knowledge_targets_json={
            "lecture": ["current_knowledge"],
            "practice_guide": ["current_knowledge"],
        }
    )
    resource = LearningResource(resource_type="lecture")

    remedial = decide_resource_matching(
        proposal_id="adjustment_1",
        path=path,
        node_gate={"can_advance": False},
        package_task=package,
        source_resource=resource,
        affected_knowledge_ids=["current_knowledge"],
        hypothesis_type="support_down",
    )
    assert remedial["decision_type"] == "remedial"
    assert remedial["requires_confirmation"] is True

    future = decide_resource_matching(
        proposal_id="adjustment_2",
        path=path,
        node_gate={"can_advance": False},
        package_task=package,
        source_resource=resource,
        affected_knowledge_ids=["future_knowledge"],
        hypothesis_type="support_down",
    )
    assert future["decision_type"] == "future_path_reprioritize"
    assert future["resource_types"] == []
    assert future["requires_confirmation"] is False
