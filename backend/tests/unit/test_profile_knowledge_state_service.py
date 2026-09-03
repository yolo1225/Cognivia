from app.agents.contracts import EvidenceRef, EvidenceType, KnowledgeAssessment
from app.agents.profile_analysis_config import AI_APP_DEV_PROFILE_V2
from app.services.profile_knowledge_state_service import (
    _learning_speed_score,
    build_knowledge_state,
    public_knowledge_state,
)


def _pair(evidence_id: str, knowledge_id: str, score: float | None, *, attempted: bool = True, confidence: float = 1.0):
    return (
        EvidenceRef(
            evidence_id=evidence_id,
            evidence_type=EvidenceType.DIAGNOSTIC_RESULT,
            summary="正式评分证据",
            knowledge_id=knowledge_id,
            confidence=confidence,
            confirmed=True,
        ),
        KnowledgeAssessment(
            assessment_id=f"assessment:{evidence_id}",
            evidence_id=evidence_id,
            knowledge_id=knowledge_id,
            score=score,
            difficulty=3,
            attempted=attempted,
            confidence=confidence,
        ),
    )


def test_state_covers_catalog_and_keeps_skipped_items_unassessed() -> None:
    evidence, assessment = _pair("ev-1", "python_api_basics", None, attempted=False)
    state = build_knowledge_state(
        config=AI_APP_DEV_PROFILE_V2,
        assessments=[assessment],
        evidence=[evidence],
        assessed_at="2026-01-01T00:00:00+00:00",
    )

    assert len(state["items"]) == 50
    assert state["coverage"]["assessed_count"] == 0
    assert all(item["status"] == "unassessed" for item in state["items"].values())


def test_uncertain_and_duplicate_evidence_are_not_consumed() -> None:
    evidence, assessment = _pair("ev-1", "python_api_basics", 1.0)
    excluded = build_knowledge_state(
        config=AI_APP_DEV_PROFILE_V2,
        assessments=[assessment],
        evidence=[evidence],
        excluded_evidence_ids={"ev-1"},
    )
    first = build_knowledge_state(
        config=AI_APP_DEV_PROFILE_V2, assessments=[assessment], evidence=[evidence]
    )
    repeated = build_knowledge_state(
        config=AI_APP_DEV_PROFILE_V2,
        assessments=[assessment],
        evidence=[evidence],
        previous_state=first,
    )

    assert excluded["accepted_evidence_ids"] == []
    assert repeated["accepted_evidence_ids"] == []
    assert repeated["items"]["python_api_basics"]["effective_weight"] == 1.0


def test_accumulation_is_order_independent_and_single_item_does_not_force_known() -> None:
    pairs = [
        _pair("ev-good", "python_api_basics", 1.0),
        _pair("ev-bad", "python_api_basics", 0.0),
    ]

    def build(ordered):
        return build_knowledge_state(
            config=AI_APP_DEV_PROFILE_V2,
            evidence=[item[0] for item in ordered],
            assessments=[item[1] for item in ordered],
            assessed_at="2026-01-01T00:00:00+00:00",
        )

    single = build(pairs[:1])
    forward = build(pairs)
    reverse = build(list(reversed(pairs)))

    assert single["items"]["python_api_basics"]["status"] == "partial_mastery"
    for key in ("mastery_score", "status", "success_weight", "failure_weight", "effective_weight"):
        assert forward["items"]["python_api_basics"][key] == reverse["items"]["python_api_basics"][key]


def test_auxiliary_mistake_redo_cannot_independently_confirm_known() -> None:
    core = _pair("core-question", "python_api_basics", 1.0)
    first = build_knowledge_state(
        config=AI_APP_DEV_PROFILE_V2,
        evidence=[core[0]],
        assessments=[core[1]],
    )
    auxiliary = _pair("mistake-redo", "python_api_basics", 1.0)
    state = build_knowledge_state(
        config=AI_APP_DEV_PROFILE_V2,
        evidence=[auxiliary[0]],
        assessments=[auxiliary[1]],
        previous_state=first,
        evidence_class_by_id={"mistake-redo": "auxiliary"},
    )

    item = state["items"]["python_api_basics"]
    assert item["core_evidence_count"] == 1
    assert item["auxiliary_evidence_count"] == 1
    assert item["status"] != "known"


def test_public_projection_hides_accumulator_parameters() -> None:
    evidence, assessment = _pair("ev-1", "python_api_basics", 0.0)
    state = build_knowledge_state(
        config=AI_APP_DEV_PROFILE_V2, assessments=[assessment], evidence=[evidence]
    )
    public = public_knowledge_state(state)

    assert public["knowledge_states"]
    assert "success_weight" not in public["knowledge_states"][0]
    assert "failure_weight" not in public["knowledge_states"][0]


def test_repeated_formal_confusion_is_distinct_from_one_off_error() -> None:
    first = _pair("ev-1", "python_api_basics", 0.5)
    second = _pair("ev-2", "python_api_basics", 0.5)
    state = build_knowledge_state(
        config=AI_APP_DEV_PROFILE_V2,
        evidence=[first[0], second[0]],
        assessments=[first[1], second[1]],
        confusion_tags_by_evidence={"ev-1": ["参数顺序"], "ev-2": ["参数顺序"]},
    )

    assert state["items"]["python_api_basics"]["status"] == "confused"


def test_learning_speed_requires_two_changed_knowledge_items() -> None:
    first = _pair("ev-1", "python_api_basics", 0.0)
    previous = build_knowledge_state(
        config=AI_APP_DEV_PROFILE_V2,
        evidence=[first[0]],
        assessments=[first[1]],
    )
    second = _pair("ev-2", "python_api_basics", 1.0)
    current = build_knowledge_state(
        config=AI_APP_DEV_PROFILE_V2,
        evidence=[second[0]],
        assessments=[second[1]],
        previous_state=previous,
    )

    score, status, evidence = _learning_speed_score(
        state=current,
        previous_state=previous,
    )

    assert score == 50
    assert status == "insufficient_longitudinal_evidence"
    assert evidence["changed_knowledge_count"] == 1


def test_learning_speed_uses_normalized_gain_and_new_opportunities() -> None:
    knowledge_ids = ["python_api_basics", "http_rest_basics"]
    initial_pairs = [_pair(f"before-{index}", knowledge_id, 0.0) for index, knowledge_id in enumerate(knowledge_ids)]
    previous = build_knowledge_state(
        config=AI_APP_DEV_PROFILE_V2,
        evidence=[pair[0] for pair in initial_pairs],
        assessments=[pair[1] for pair in initial_pairs],
    )
    follow_up_pairs = [_pair(f"after-{index}", knowledge_id, 1.0) for index, knowledge_id in enumerate(knowledge_ids)]
    current = build_knowledge_state(
        config=AI_APP_DEV_PROFILE_V2,
        evidence=[pair[0] for pair in follow_up_pairs],
        assessments=[pair[1] for pair in follow_up_pairs],
        previous_state=previous,
    )

    score, status, evidence = _learning_speed_score(
        state=current,
        previous_state=previous,
    )

    assert status == "assessed"
    assert score > 50
    assert evidence["opportunity_count"] == 2
    assert evidence["changed_knowledge_count"] == 2
    assert evidence["normalized_gain"] > 0


def test_learning_speed_preserves_negative_mastery_change() -> None:
    knowledge_ids = ["python_api_basics", "http_rest_basics"]
    initial_pairs = [_pair(f"before-{index}", knowledge_id, 1.0) for index, knowledge_id in enumerate(knowledge_ids)]
    previous = build_knowledge_state(
        config=AI_APP_DEV_PROFILE_V2,
        evidence=[pair[0] for pair in initial_pairs],
        assessments=[pair[1] for pair in initial_pairs],
    )
    follow_up_pairs = [_pair(f"after-{index}", knowledge_id, 0.0) for index, knowledge_id in enumerate(knowledge_ids)]
    current = build_knowledge_state(
        config=AI_APP_DEV_PROFILE_V2,
        evidence=[pair[0] for pair in follow_up_pairs],
        assessments=[pair[1] for pair in follow_up_pairs],
        previous_state=previous,
    )

    score, status, evidence = _learning_speed_score(
        state=current,
        previous_state=previous,
    )

    assert status == "assessed"
    assert score < 50
    assert evidence["normalized_gain"] < 0
