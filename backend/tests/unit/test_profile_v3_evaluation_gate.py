from __future__ import annotations

from dataclasses import replace

import pytest

import app.scripts.evaluate_profile_v3 as evaluation
from app.agents.contracts import ProfileType
from app.services.profile_analysis_service import analyze_profile as _analyze_profile
from app.agents.profile_analysis_config import AI_APP_DEV_PROFILE_V2
from app.services.profile_v3_fixture_service import (
    ProfileFixtureError,
    rendered_case_records,
)


def analyze_profile(node_input):
    return _analyze_profile(node_input, config=AI_APP_DEV_PROFILE_V2)


def _report_with_mutation(mutator):
    target_case_id = "accept-initial-01"

    def analyzer(request):
        output = analyze_profile(request)
        return mutator(output) if request.task_id == target_case_id else output

    return evaluation.evaluate_profile_v3(analyzer=analyzer), target_case_id


@pytest.mark.parametrize(
    ("category", "mutator"),
    [
        (
            "evidence_policy",
            lambda output: output.model_copy(update={"changed_dimensions": ["invalid_dimension"]}),
        ),
        (
            "profile_calculation",
            lambda output: output.model_copy(
                update={
                    "profile": output.profile.model_copy(
                        update={"profile_type": ProfileType.ADVANCED}
                    )
                }
            ),
        ),
        (
            "affected_scope",
            lambda output: output.model_copy(
                update={
                    "affected_scope": output.affected_scope.model_copy(
                        update={"path_node_ids": ["unprovable-path"]}
                    )
                }
            ),
        ),
        (
            "retrieval_plan",
            lambda output: output.model_copy(
                update={
                    "retrieval_plan": output.retrieval_plan.model_copy(
                        update={
                            "target_difficulty": 1
                            if output.retrieval_plan.target_difficulty != 1
                            else 2
                        }
                    )
                }
            ),
        ),
    ],
)
def test_evaluation_attributes_semantic_failures(category, mutator) -> None:
    report, case_id = _report_with_mutation(mutator)

    assert report["status"] == "failed"
    assert case_id in report["failure_attribution"][category]
    assert case_id in report["acceptance"]["failed_case_ids"]


def test_evaluation_attributes_invalid_input_preparation() -> None:
    case = rendered_case_records()[0]
    invalid_case = replace(case, payload={"task_id": case.case_id})

    request, output, categories = evaluation._run_case(invalid_case, analyze_profile)

    assert request is None
    assert output is None
    assert categories == {"input_preparation"}


def test_main_exits_nonzero_for_a_failed_quality_report(monkeypatch, capsys) -> None:
    monkeypatch.setattr(evaluation, "evaluate_profile_v3", lambda: {"status": "failed"})

    with pytest.raises(SystemExit, match="1"):
        evaluation.main()

    assert '"status": "failed"' in capsys.readouterr().out


def test_main_exits_nonzero_when_the_fixture_gate_fails(monkeypatch, capsys) -> None:
    def reject_manifest() -> None:
        raise ProfileFixtureError("acceptance_fixture_hash_mismatch")

    monkeypatch.setattr(evaluation, "validate_acceptance_manifest", reject_manifest)

    with pytest.raises(SystemExit, match="1"):
        evaluation.main()

    assert "acceptance_fixture_hash_mismatch" in capsys.readouterr().out


def test_current_frozen_baseline_meets_all_quality_thresholds() -> None:
    report = evaluation.evaluate_profile_v3()

    assert report["status"] == "passed"
    assert report["development"]["numerator"] == 30
    assert report["acceptance"]["numerator"] == 20
    assert report["metrics"]["deterministic_output_rate"]["numerator"] == 100
    assert report["p95_ms"] <= report["thresholds"]["maximum_p95_ms"]
    for metric_name, minimum_rate in evaluation.MINIMUM_RATES.items():
        assert report["metrics"][metric_name]["rate"] >= minimum_rate
