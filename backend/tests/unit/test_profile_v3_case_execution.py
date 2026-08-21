from __future__ import annotations

from app.agents.contracts import AnalyzeProfileInput
from app.scripts.evaluate_profile_v3 import evaluate_profile_v3
from app.services.profile_analysis_service import analyze_profile as _analyze_profile
from app.agents.profile_analysis_config import AI_APP_DEV_PROFILE_V2
from app.services.profile_v3_fixture_service import rendered_cases


def analyze_profile(node_input):
    return _analyze_profile(node_input, config=AI_APP_DEV_PROFILE_V2)


def test_profile_v3_cases_match_frozen_algorithm_baseline() -> None:
    cases = rendered_cases()

    assert len(cases) == 50
    for case_id, payload, expected in cases:
        output = analyze_profile(AnalyzeProfileInput.model_validate(payload))
        actual = {
            "profile_update_required": output.profile_update_required,
            "changed_dimensions": output.changed_dimensions,
            "profile_type": output.profile.profile_type.value,
            "weak_knowledge_ids": [item.knowledge_id for item in output.profile.weak_knowledge],
            "retrieval_strategy": output.retrieval_plan.strategy.value,
            "target_difficulty": output.retrieval_plan.target_difficulty,
            "priority_knowledge_ids": output.retrieval_plan.priority_knowledge_ids,
            "prerequisite_knowledge_ids": output.retrieval_plan.prerequisite_knowledge_ids,
            "needs_generation": output.needs_generation,
        }
        assert actual == expected, case_id


def test_profile_v3_evaluation_uses_the_frozen_fixture_gate() -> None:
    report = evaluate_profile_v3()

    assert report["case_count"] == 50
    assert report["development"] == {
        "numerator": 30,
        "denominator": 30,
        "rate": 1.0,
        "failed_case_ids": [],
    }
    assert report["acceptance"] == {
        "numerator": 20,
        "denominator": 20,
        "rate": 1.0,
        "failed_case_ids": [],
    }
    assert report["generated_at"]
