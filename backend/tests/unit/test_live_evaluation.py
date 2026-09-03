import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("evaluation_script", ROOT / "test_script" / "evaluate.py")
assert SPEC and SPEC.loader
evaluation_script = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluation_script)


def _formal_cases() -> list[dict]:
    cases = []
    for index in range(50):
        cases.append(
            {
                "case_id": f"EVAL-{index + 1:03d}",
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
        )
    return cases


def test_live_result_merge_keeps_gold_and_replaces_only_observation() -> None:
    cases = [
        {
            "case_id": "EVAL-001",
            "expected_review_conclusion": "passed",
            "expected_profile_decision": "no_change",
            "observed_result": {"determinable": True, "latency_ms": 1},
        }
    ]
    run = {
        "run_id": "live-test",
        "results": [
            {
                "case_id": "EVAL-001",
                "task_status": "completed",
                "observed_result": {
                    "determinable": True,
                    "generated_fact_count": 2,
                    "hallucinated_fact_count": 0,
                    "difficulty_matched": True,
                    "covered_core_knowledge_count": 1,
                    "target_core_knowledge_count": 1,
                    "review_conclusion": "passed",
                    "profile_decision": "no_change",
                    "latency_ms": 200,
                    "agent_latency_ms": {"review_resource": 80},
                },
            }
        ],
    }

    merged = evaluation_script.merge_live_results(cases, run)
    result = evaluation_script.evaluate(
        merged,
        {"kb-test"},
        run_mode="live",
        run_metadata=run,
    )

    assert cases[0]["observed_result"]["latency_ms"] == 1
    assert merged[0]["observed_result"]["latency_ms"] == 200
    assert result["run_mode"] == "live"
    assert result["metrics"]["hallucination_rate"]["ratio"] == 0
    assert result["metrics"]["agent_latency_ms"]["review_resource"] == {
        "p50": 80,
        "p95": 80,
    }
    assert result["metrics"]["task_success_rate"] == {
        "numerator": 1,
        "denominator": 1,
        "ratio": 1.0,
    }


def test_formal_acceptance_reports_nonperfect_diagnostics_without_failing() -> None:
    cases = _formal_cases()
    observed = cases[0]["observed_result"]
    observed["hallucinated_fact_count"] = 1
    observed["evidence_insufficient_claim_count"] = 1
    observed["unresolved_claim_count"] = 1
    observed["review_conclusion"] = "revision_required"
    observed["profile_decision"] = "regenerate"

    result = evaluation_script.evaluate(cases, {"kb-test"})

    assert result["status"] == "passed"
    assert result["metrics"]["hallucination_rate"]["ratio"] == 0.01
    assert result["competition_acceptance"]["accepted"] is True
    assert set(result["competition_acceptance"]["diagnostic_findings"]) == {
        "no_evidence_insufficient",
        "no_unresolved_claims",
        "review_decisions_match",
        "profile_decisions_match",
    }


def test_no_change_case_is_excluded_from_resource_difficulty_denominator() -> None:
    cases = _formal_cases()
    cases[-1]["expected_review_conclusion"] = "no_change"
    cases[-1]["observed_result"].update(
        {
            "generated_fact_count": 0,
            "difficulty_matched": None,
            "covered_core_knowledge_count": 0,
            "target_core_knowledge_count": 0,
            "review_conclusion": "no_change",
        }
    )

    result = evaluation_script.evaluate(cases, {"kb-test"})

    assert result["metrics"]["difficulty_match_accuracy"] == {
        "numerator": 49,
        "denominator": 49,
        "ratio": 1.0,
    }
    assert result["metrics"]["difficulty_not_applicable_case_count"] == 1
    assert result["failed_case_ids"]["difficulty"] == []
