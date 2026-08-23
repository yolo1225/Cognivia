from app.agents.contracts import AnalyzeProfileOutput
from app.models import KnowledgeItem, LearnerProfile
from app.services.contract_mapping import profile_snapshot
from app.services.profile_semantics_service import apply_confirmed_knowledge_semantics


def _profile(*, weak: bool = True) -> LearnerProfile:
    return LearnerProfile(
        public_id="profile_1",
        learner_id=1,
        domain_code="ai_app_dev",
        profile_version=2,
        ability_profile_json={
            "profile_type": "beginner",
            "theory": 60,
            "practice": 55,
            "problem_solving": 50,
            "knowledge_breadth": 45,
            "learning_speed": 65,
            "blind_spot_ids": ["knowledge_1"] if weak else [],
        },
        weak_knowledge_json=[
            {
                "knowledge_id": "knowledge_1",
                "name": "Prompt 上下文设计",
                "category": "prompt_engineering",
                "weakness_level": 3,
                "mastery_type": "confused",
                "prerequisite_ids": [],
                "evidence_ids": ["diagnostic:1"],
                "reason": "诊断中存在混淆",
            }
        ] if weak else [],
    )


def _knowledge() -> KnowledgeItem:
    return KnowledgeItem(
        public_id="knowledge_1",
        domain_code="ai_app_dev",
        name="Prompt 上下文设计",
        category="prompt_engineering",
        difficulty=3,
        content_md="content",
        source_title="source",
        license_note="test",
    )


def _unchanged_analysis(profile: LearnerProfile) -> AnalyzeProfileOutput:
    return AnalyzeProfileOutput.model_validate(
        {
            "task_id": "proposal_1",
            "profile": profile_snapshot(profile).model_dump(mode="json"),
            "profile_update_required": False,
            "changed_dimensions": [],
            "evidence_refs": [],
            "confidence": 0.7,
            "decision_reason": "高层画像暂无充分变化证据",
            "affected_scope": {
                "knowledge_ids": [],
                "path_node_ids": [],
                "resource_ids": [],
            },
            "retrieval_plan": {
                "strategy": "consolidation",
                "target_difficulty": 3,
                "resource_types": ["lecture"],
                "priority_knowledge_ids": ["knowledge_1"],
                "prerequisite_knowledge_ids": [],
                "query_terms": ["Prompt 上下文设计"],
            },
            "needs_generation": False,
            "resource_knowledge_targets": {},
        }
    )


def test_confirmed_mastery_removes_weak_and_blind_state() -> None:
    profile = _profile()
    normalized, summary = apply_confirmed_knowledge_semantics(
        original=profile,
        analysis=_unchanged_analysis(profile),
        hypothesis_type="mastery_up",
        knowledge=_knowledge(),
        evidence_id="answer_record:1",
        path_node_id="knowledge:knowledge_1",
    )

    assert normalized.profile_update_required is True
    assert normalized.profile.profile_version == 3
    assert normalized.profile.weak_knowledge == []
    assert normalized.profile.blind_spot_ids == []
    assert normalized.profile.ability_scores == profile_snapshot(profile).ability_scores
    assert normalized.evidence_refs[0].evidence_id == "answer_record:1"
    assert summary["after_state"] == "known"
    assert summary["removed_from_weak_knowledge"] is True
    assert summary["removed_from_blind_spots"] is True


def test_confirmed_support_adds_unmastered_level_four() -> None:
    profile = _profile(weak=False)
    normalized, summary = apply_confirmed_knowledge_semantics(
        original=profile,
        analysis=_unchanged_analysis(profile),
        hypothesis_type="support_down",
        knowledge=_knowledge(),
        evidence_id="answer_record:2",
        path_node_id="knowledge:knowledge_1",
    )

    weak = normalized.profile.weak_knowledge[0]
    assert weak.knowledge_id == "knowledge_1"
    assert weak.mastery_type.value == "unmastered"
    assert weak.weakness_level == 4
    assert normalized.profile.blind_spot_ids == ["knowledge_1"]
    assert summary["before_state"] == "not_weak"
    assert summary["after_state"] == "unmastered"


def test_already_known_mastery_does_not_create_empty_change() -> None:
    profile = _profile(weak=False)
    normalized, summary = apply_confirmed_knowledge_semantics(
        original=profile,
        analysis=_unchanged_analysis(profile),
        hypothesis_type="mastery_up",
        knowledge=_knowledge(),
        evidence_id="answer_record:3",
        path_node_id="knowledge:knowledge_1",
    )

    assert normalized.profile_update_required is False
    assert normalized.profile.profile_version == 2
    assert normalized.evidence_refs == []
    assert summary["profile_changed"] is False
