from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


SCRIPT_DIR = Path(__file__).resolve().parents[3] / "test_script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_live  # noqa: E402
import evaluate as evaluator  # noqa: E402
import stability  # noqa: E402


def _case(scenario_type: str = "feedback_revision") -> dict:
    return {
        "case_id": "V4-EVAL-041",
        "scenario_type": scenario_type,
        "profile_snapshot": {"profile_type": "intermediate"},
        "resource_type": "practice_guide",
        "target_core_knowledge_ids": ["rag_pipeline_overview"],
    }


def _resource(resource_type: str, resource_id: str, membership_type: str) -> dict:
    return {
        "resource_type": resource_type,
        "resource_id": resource_id,
        "review_status": "passed",
        "membership_type": membership_type,
    }


def _acceptance_summary(
    *,
    case_count: int = 15,
    evaluated_case_count: int = 15,
    hallucination_rate: float = 0.01,
    difficulty_rate: float = 0.90,
    coverage_rate: float = 0.95,
    evidence_insufficient: int = 1,
    unresolved: int = 1,
    review_rate: float = 0.90,
    profile_rate: float = 0.90,
) -> dict:
    return {
        "case_count": case_count,
        "evaluated_case_count": evaluated_case_count,
        "metrics": {
            "hallucination_rate": {"ratio": hallucination_rate},
            "difficulty_match_accuracy": {"ratio": difficulty_rate},
            "core_knowledge_coverage": {"ratio": coverage_rate},
            "evidence_insufficient_claims": {"count": evidence_insufficient},
            "unresolved_claims": {"count": unresolved},
            "review_decision_accuracy": {"ratio": review_rate},
            "profile_decision_accuracy": {"ratio": profile_rate},
        },
    }


def test_stage_acceptance_uses_competition_thresholds_not_perfect_diagnostics() -> None:
    acceptance = run_live._stage_acceptance(_acceptance_summary(), 15)

    assert acceptance["accepted"] is True
    assert acceptance["failed_checks"] == []
    assert set(acceptance["diagnostic_findings"]) == {
        "no_evidence_insufficient",
        "no_unresolved_claims",
        "review_decisions_match",
        "profile_decisions_match",
    }
    assert acceptance["checks"]["no_unresolved_claims"] is False


@pytest.mark.parametrize(
    ("overrides", "failed_check"),
    [
        ({"hallucination_rate": 0.05}, "hallucination_rate_below_5_percent"),
        ({"difficulty_rate": 0.849}, "difficulty_match_at_least_85_percent"),
        ({"coverage_rate": 0.899}, "core_coverage_at_least_90_percent"),
        ({"case_count": 14}, "all_cases_present"),
        ({"evaluated_case_count": 14}, "all_cases_determinable"),
    ],
)
def test_stage_acceptance_rejects_only_failed_competition_gates(
    overrides: dict, failed_check: str
) -> None:
    acceptance = run_live._stage_acceptance(_acceptance_summary(**overrides), 15)

    assert acceptance["accepted"] is False
    assert failed_check in acceptance["failed_checks"]


def test_feedback_case_uses_target_baseline_then_evaluates_feedback_task(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    baseline = {
        "task_id": "task_baseline",
        "status": "completed",
        "resources": [
            _resource("lecture", "res_lecture", "generated"),
            _resource("practice_guide", "res_practice", "generated"),
            _resource("graded_quiz", "res_quiz", "generated"),
        ],
    }
    final = {"task_id": "task_feedback", "status": "completed", "resources": []}

    def fake_api(base_url, method, path, payload=None, **kwargs):
        calls.append((method, path))
        if path == "/generation-tasks":
            assert payload["resource_types"] == ["practice_guide"]
            return {"task_id": "task_baseline"}
        if path == "/resources/res_practice/feedback":
            return {"recommended_action": "review", "task_id": "task_feedback"}
        if path == "/generation-tasks/task_feedback/agent-runs":
            return []
        raise AssertionError(path)

    monkeypatch.setattr(run_live, "_api_json", fake_api)
    monkeypatch.setattr(
        run_live,
        "_poll_task",
        lambda _base, task_id, _timeout: baseline if task_id == "task_baseline" else final,
    )
    monkeypatch.setattr(
        run_live,
        "_observed_result",
        lambda case, task, runs, elapsed_ms: {"determinable": True},
    )

    result = run_live.run_case("http://test/api/v1", _case(), 30)

    assert result["baseline_task_id"] == "task_baseline"
    assert result["task_id"] == "task_feedback"
    assert result["scenario_type"] == "feedback_revision"
    assert ("POST", "/resources/res_practice/feedback") in calls


def test_challenge_case_uses_tutoring_branch(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    baseline = {
        "task_id": "task_baseline",
        "status": "completed",
        "resources": [
            _resource("lecture", "res_lecture", "generated"),
            _resource("practice_guide", "res_practice", "generated"),
            _resource("graded_quiz", "res_quiz", "generated"),
        ],
    }
    final = {"task_id": "task_challenge", "status": "completed", "resources": []}

    def fake_api(base_url, method, path, payload=None, **kwargs):
        calls.append((method, path))
        if path == "/generation-tasks":
            assert payload["resource_types"] == ["practice_guide"]
            return {"task_id": "task_baseline"}
        if path == "/tutoring/sessions":
            return {"session_id": "session_eval"}
        if path == "/tutoring/sessions/session_eval/messages":
            assert kwargs["timeout"] == 30
            assert payload["evidence"] == [
                {
                    "evidence_id": "V4-EVAL-041-validated-mastery",
                    "evidence_type": "validated_behavior",
                    "summary": "版本化评测案例提供的已确认迁移任务完成行为",
                    "knowledge_id": "rag_pipeline_overview",
                    "confidence": 0.9,
                    "confirmed": True,
                }
            ]
            return {
                "recommended_action": "challenge",
                "feedback_id": 42,
                "task_id": None,
            }
        if path == "/generation-tasks/feedback/42/confirm":
            return {"task_id": "task_challenge"}
        if path == "/generation-tasks/task_challenge/agent-runs":
            return []
        raise AssertionError(path)

    monkeypatch.setattr(run_live, "_api_json", fake_api)
    monkeypatch.setattr(
        run_live,
        "_poll_task",
        lambda _base, task_id, _timeout: baseline if task_id == "task_baseline" else final,
    )
    monkeypatch.setattr(
        run_live,
        "_observed_result",
        lambda case, task, runs, elapsed_ms: {"determinable": True},
    )

    result = run_live.run_case("http://test/api/v1", _case("challenge_task"), 30)

    assert result["baseline_task_id"] == "task_baseline"
    assert result["task_id"] == "task_challenge"
    assert ("POST", "/tutoring/sessions/session_eval/messages") in calls
    assert ("POST", "/generation-tasks/feedback/42/confirm") in calls


def test_no_profile_change_is_determinable_without_generated_resource() -> None:
    observed = run_live._observed_result(
        _case("challenge_task"),
        {"status": "completed", "decision": "no_change"},
        [
            {
                "input_summary": {"step": "analyze_profile"},
                "output_summary": {"profile_update_required": False},
                "duration_ms": 12,
            }
        ],
        25,
    )

    assert observed["determinable"] is True
    assert observed["review_conclusion"] == "no_change"
    assert observed["generated_fact_count"] == 0
    assert observed["target_core_knowledge_count"] == 0
    assert observed["difficulty_matched"] is None
    assert observed["failure_category"] is None


def test_resume_rejects_changed_rag_configuration(tmp_path: Path, monkeypatch) -> None:
    run_id = "live-formal-20260819T010203Z"
    monkeypatch.setattr(run_live, "RUN_DIR", tmp_path)
    (tmp_path / f"{run_id}.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "run_mode": "live",
                "stage": "formal",
                "diagnostic_case_id": None,
                "model_configuration": {"generation_model": "model"},
                "knowledge_base_versions": ["kb-v4"],
                "rag_configuration": {"index_version": "old"},
                "case_set_sha256": "sha256:cases",
                "full_suite_case_sha256": "sha256:full-suite",
                "results": [],
                "complete": False,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="rag_configuration"):
        run_live._resume_run(
            run_id,
            stage="formal",
            diagnostic_case_id=None,
            selected_case_ids={"V4-EVAL-001"},
            model_configuration={"generation_model": "model"},
            knowledge_base_versions=["kb-v4"],
            rag_configuration={"index_version": "new"},
            case_set_sha256="sha256:cases",
            full_suite_case_sha256="sha256:full-suite",
        )


def test_resume_reopens_complete_run_with_indeterminable_case(
    tmp_path: Path, monkeypatch
) -> None:
    run_id = "live-formal-20260819T010203Z"
    monkeypatch.setattr(run_live, "RUN_DIR", tmp_path)
    metadata = {
        "run_id": run_id,
        "run_mode": "live",
        "stage": "formal",
        "diagnostic_case_id": None,
        "model_configuration": {"generation_model": "model"},
        "knowledge_base_versions": ["kb-v4"],
        "rag_configuration": {"index_version": "index-v6"},
        "case_set_sha256": "sha256:cases",
        "full_suite_case_sha256": "sha256:full-suite",
    }
    (tmp_path / f"{run_id}.json").write_text(
        json.dumps(
            {
                **metadata,
                "complete": True,
                "valid": False,
                "stage_acceptance": {"accepted": False},
                "results": [
                    {
                        "case_id": "V4-EVAL-001",
                        "observed_result": {"determinable": False},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    _path, resumed = run_live._resume_run(
        run_id,
        stage="formal",
        diagnostic_case_id=None,
        selected_case_ids={"V4-EVAL-001"},
        model_configuration=metadata["model_configuration"],
        knowledge_base_versions=metadata["knowledge_base_versions"],
        rag_configuration=metadata["rag_configuration"],
        case_set_sha256=metadata["case_set_sha256"],
        full_suite_case_sha256=metadata["full_suite_case_sha256"],
    )

    assert resumed["complete"] is False
    assert resumed["valid"] is False
    assert "stage_acceptance" not in resumed


def test_prior_stage_requires_current_full_suite_models_and_rag(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(run_live, "RUN_DIR", tmp_path)
    current = {
        "full_suite_case_sha256": "sha256:full-suite",
        "model_configuration": {"generation_model": "model-v6"},
        "knowledge_base_versions": ["kb-v4"],
        "rag_configuration": {"index_version": "index-v6"},
    }
    report = {
        "stage": "smoke",
        "valid": True,
        "diagnostic_case_id": None,
        "stage_acceptance": {"accepted": True},
        **current,
    }
    report_path = tmp_path / "live-smoke-20260819T010203Z.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    assert run_live._prior_stage_exists("regression", **current)

    stale_variants = [
        {**current, "full_suite_case_sha256": "sha256:changed-suite"},
        {**current, "model_configuration": {"generation_model": "changed-model"}},
        {**current, "knowledge_base_versions": ["changed-kb"]},
        {**current, "rag_configuration": {"index_version": "changed-index"}},
    ]
    for stale in stale_variants:
        assert not run_live._prior_stage_exists("regression", **stale)


def test_prior_stage_rejects_legacy_report_without_full_suite_hash(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(run_live, "RUN_DIR", tmp_path)
    (tmp_path / "legacy.json").write_text(
        json.dumps(
            {
                "stage": "smoke",
                "valid": True,
                "diagnostic_case_id": None,
                "stage_acceptance": {"accepted": True},
                "model_configuration": {"generation_model": "model-v6"},
                "knowledge_base_versions": ["kb-v4"],
                "rag_configuration": {"index_version": "index-v6"},
            }
        ),
        encoding="utf-8",
    )


def test_live_summary_preserves_reproducibility_configuration() -> None:
    case = {
        "case_id": "V4-EVAL-001",
        "expected_review_conclusion": "passed",
        "expected_profile_decision": "no_change",
        "observed_result": {
            "determinable": True,
            "generated_fact_count": 2,
            "hallucinated_fact_count": 0,
            "evidence_insufficient_claim_count": 0,
            "unresolved_claim_count": 0,
            "difficulty_matched": True,
            "covered_core_knowledge_count": 1,
            "target_core_knowledge_count": 1,
            "review_conclusion": "passed",
            "profile_decision": "no_change",
            "latency_ms": 10,
        },
    }
    run_metadata = {
        "run_id": "live-smoke-20260819T010203Z",
        "stage": "smoke",
        "diagnostic_case_id": None,
        "model_configuration": {"generation_model": "model-v6"},
        "rag_configuration": {"index_version": "index-v6"},
        "case_set_sha256": "sha256:smoke",
        "full_suite_case_sha256": "sha256:full-suite",
        "complete": True,
        "valid": True,
    }

    report = evaluator.evaluate(
        [case], {"kb-v4"}, run_mode="live", run_metadata=run_metadata
    )

    for key, value in run_metadata.items():
        expected_key = {"complete": "run_complete", "valid": "run_valid"}.get(key, key)
        assert report[expected_key] == value

    assert not run_live._prior_stage_exists(
        "regression",
        full_suite_case_sha256="sha256:full-suite",
        model_configuration={"generation_model": "model-v6"},
        knowledge_base_versions=["kb-v4"],
        rag_configuration={"index_version": "index-v6"},
    )


def test_stability_partial_package_requires_one_generated_and_two_inherited() -> None:
    source = {
        "lecture": _resource("lecture", "res_lecture", "generated"),
        "practice_guide": _resource("practice_guide", "res_practice", "generated"),
        "graded_quiz": _resource("graded_quiz", "res_quiz", "generated"),
    }
    invalid_partial = {
        "source_task_id": "task_source",
        "trigger_type": "resource_feedback",
        "event_type": "resource_feedback",
        "resources": [
            _resource("lecture", "res_lecture", "inherited"),
            _resource("practice_guide", "res_practice_new", "generated"),
            _resource("graded_quiz", "res_quiz_new", "generated"),
        ],
    }

    with pytest.raises(AssertionError, match="generate one and inherit two"):
        stability._assert_partial_package(
            invalid_partial,
            source_task_id="task_source",
            source_resources=source,
        )


def test_evidence_gap_with_valid_case_and_capability_is_program_defect(monkeypatch) -> None:
    case = _case("initial_generation")
    case["gold_standard"] = {
        "required_source_ids": ["rag_pipeline_overview"],
        "required_evidence_capability": "operation",
    }
    monkeypatch.setattr(
        run_live,
        "_knowledge_capabilities",
        lambda: {"rag_pipeline_overview": {"concept", "operation"}},
    )
    result = run_live._classify_failure(
        case,
        {"failure_reason": "evidence_gap"},
        [],
    )

    assert result["failure_category"] == "program_defect"
    assert result["classification_confidence"] == "high"


def test_evidence_gap_with_missing_capability_is_knowledge_data_gap(monkeypatch) -> None:
    case = _case("initial_generation")
    case["gold_standard"] = {
        "required_source_ids": ["rag_pipeline_overview"],
        "required_evidence_capability": "operation",
    }
    monkeypatch.setattr(
        run_live,
        "_knowledge_capabilities",
        lambda: {"rag_pipeline_overview": {"concept"}},
    )

    result = run_live._classify_failure(
        case,
        {"failure_reason": "evidence_gap"},
        [],
    )

    assert result["failure_category"] == "knowledge_data_gap"


def test_invalid_case_is_not_misclassified_as_knowledge_gap() -> None:
    case = _case("initial_generation")
    case["gold_standard"] = {
        "required_source_ids": ["different_target"],
        "required_evidence_capability": "operation",
    }

    result = run_live._classify_failure(
        case,
        {"failure_reason": "evidence_gap"},
        [],
    )

    assert result["failure_category"] == "case_defect"


def test_model_structure_failure_is_external_service_failure() -> None:
    result = run_live._classify_failure(
        None,
        {"failure_reason": "generated_structure_validation_failed"},
        [],
    )

    assert result["failure_category"] == "external_service_failure"


def test_case_suite_preflight_rejects_missing_operation_evidence(monkeypatch) -> None:
    case = _case("initial_generation")
    case["gold_standard"] = {
        "required_source_ids": ["rag_pipeline_overview"],
        "required_evidence_capability": "operation",
    }
    monkeypatch.setattr(
        run_live,
        "_knowledge_capabilities",
        lambda: {"rag_pipeline_overview": {"concept"}},
    )

    with pytest.raises(ValueError, match="knowledge_data_gap:V4-EVAL-041"):
        run_live._validate_case_evidence([case])


def test_stability_failure_checkpoint_survives_agent_run_api_failure(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(stability, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(
        stability,
        "_api_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(run_live.ApiFailure("offline")),
    )
    report = {"run_id": "stability-test", "results": [], "status": "running"}

    stability._record_failure(
        report,
        report["results"],
        base_url="http://test/api/v1",
        task={"task_id": "task-failed", "failure_reason": "candidate_index_stale"},
        index=1,
        kind="full_generation",
        error=AssertionError("failed"),
    )

    saved = json.loads((tmp_path / "stability-test.json").read_text(encoding="utf-8"))
    assert saved["status"] == "failed"
    assert saved["results"][0]["failure_category"] == "operations_failure"
