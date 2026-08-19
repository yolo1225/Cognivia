"""Run deterministic V3 profile evaluation and enforce the frozen quality gate."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import time
from statistics import median
from typing import Any, Callable

from pydantic import ValidationError

from app.agents.contracts import AnalyzeProfileInput, AnalyzeProfileOutput, EvidenceType
from app.agents.profile_analysis_config import AI_APP_DEV_PROFILE_V2
from app.services.profile_analysis_service import ProfileAnalysisError, analyze_profile
from app.services.profile_v3_fixture_service import (
    ProfileFixtureError,
    RenderedProfileCase,
    rendered_case_records,
    validate_acceptance_manifest,
)


REPORT_SCHEMA_VERSION = "profile-v3-evaluation-v3"
ALGORITHM_VERSION = "profile_analysis_service_v3"
DETERMINISTIC_RUNS = 100
MAX_P95_MS = 500.0
MINIMUM_RATES = {
    "contract_valid_output_rate": 1.0,
    "single_subjective_feedback_no_update_rate": 1.0,
    "strong_evidence_update_decision_accuracy": 0.95,
    "weak_knowledge_identification_accuracy": 0.90,
    "retrieval_strategy_accuracy": 0.95,
    "target_difficulty_accuracy": 0.90,
    "priority_prerequisite_completeness": 0.95,
    "deterministic_output_rate": 1.0,
}
FAILURE_CATEGORIES = (
    "input_preparation",
    "evidence_policy",
    "profile_calculation",
    "affected_scope",
    "retrieval_plan",
)

Analyzer = Callable[[AnalyzeProfileInput], AnalyzeProfileOutput]


def _actual(output: AnalyzeProfileOutput) -> dict[str, Any]:
    return {
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


def _percentile(values: list[float], percentile: float) -> float:
    return values[max(0, min(len(values) - 1, round((len(values) - 1) * percentile)))]


def _case_metric(total: int, failed_case_ids: list[str]) -> dict[str, Any]:
    passed = total - len(failed_case_ids)
    return {
        "numerator": passed,
        "denominator": total,
        "rate": round(passed / total, 4) if total else 0.0,
        "failed_case_ids": failed_case_ids,
    }


def _metric(total: int, passed_case_ids: list[str], all_case_ids: list[str]) -> dict[str, Any]:
    failed_case_ids = [case_id for case_id in all_case_ids if case_id not in passed_case_ids]
    return {
        "numerator": len(passed_case_ids),
        "denominator": total,
        "rate": round(len(passed_case_ids) / total, 4) if total else 0.0,
        "failed_case_ids": failed_case_ids,
    }


def _case_group(case_id: str) -> str:
    return "acceptance" if case_id.startswith("accept-") else "development"


def _has_strong_assessment(request: AnalyzeProfileInput) -> bool:
    evidence = list(request.feedback_evidence)
    if request.diagnostic_summary is not None:
        evidence.extend(request.diagnostic_summary.evidence)
    evidence_by_id = {item.evidence_id: item for item in evidence}
    allowed_types = {
        EvidenceType.DIAGNOSTIC_RESULT,
        EvidenceType.SCORED_QUIZ,
    }
    return any(
        assessment.attempted
        and assessment.score is not None
        and (source := evidence_by_id.get(assessment.evidence_id)) is not None
        and source.confirmed
        and source.evidence_type in allowed_types
        for assessment in request.knowledge_assessments
    )


def _affected_scope_errors(
    request: AnalyzeProfileInput, output: AnalyzeProfileOutput
) -> list[str]:
    """Check only scope facts provable from the frozen input and configuration."""
    scope = output.affected_scope
    catalog = AI_APP_DEV_PROFILE_V2.knowledge_catalog
    errors: list[str] = []
    if scope.path_node_ids or scope.resource_ids:
        errors.append("unprovable_path_or_resource_scope")
    if any(knowledge_id not in catalog for knowledge_id in scope.knowledge_ids):
        errors.append("unknown_affected_knowledge")

    previous_weak = {item.knowledge_id for item in request.current_profile.weak_knowledge}
    current_weak = {item.knowledge_id for item in output.profile.weak_knowledge}
    changed_ids = previous_weak ^ current_weak
    changed_ids |= set(request.current_profile.blind_spot_ids) ^ set(output.profile.blind_spot_ids)
    required_ids = set(changed_ids)
    for knowledge_id in changed_ids:
        if knowledge_id in catalog:
            required_ids.update(catalog[knowledge_id].prerequisite_ids)
    if not required_ids.issubset(scope.knowledge_ids):
        errors.append("missing_provable_affected_knowledge")
    if not output.profile_update_required and scope.knowledge_ids:
        errors.append("unchanged_profile_has_affected_knowledge")
    return errors


def _case_categories(
    request: AnalyzeProfileInput,
    output: AnalyzeProfileOutput,
    expected: dict[str, Any],
) -> set[str]:
    actual = _actual(output)
    categories: set[str] = set()
    if any(
        actual[field] != expected[field]
        for field in ("profile_update_required", "changed_dimensions")
    ):
        categories.add("evidence_policy")
    if any(
        actual[field] != expected[field]
        for field in ("profile_type", "weak_knowledge_ids")
    ) or output.profile.profile_version != (
        request.current_profile.profile_version + int(output.profile_update_required)
    ):
        categories.add("profile_calculation")
    if _affected_scope_errors(request, output):
        categories.add("affected_scope")
    if any(
        actual[field] != expected[field]
        for field in (
            "retrieval_strategy",
            "target_difficulty",
            "priority_knowledge_ids",
            "prerequisite_knowledge_ids",
            "needs_generation",
        )
    ):
        categories.add("retrieval_plan")
    return categories


def _run_case(
    case: RenderedProfileCase, analyzer: Analyzer
) -> tuple[AnalyzeProfileInput | None, AnalyzeProfileOutput | None, set[str]]:
    try:
        request = AnalyzeProfileInput.model_validate(case.payload)
        raw_output = analyzer(request)
        output = AnalyzeProfileOutput.model_validate(raw_output.model_dump(mode="python"))
    except (ProfileAnalysisError, ValidationError, ValueError, AttributeError):
        return None, None, {"input_preparation"}
    return request, output, _case_categories(request, output, case.expected)


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _report_passes(report: dict[str, Any]) -> bool:
    if report["development"]["rate"] != 1.0 or report["acceptance"]["rate"] != 1.0:
        return False
    for metric_name, minimum_rate in MINIMUM_RATES.items():
        if report["metrics"][metric_name]["rate"] < minimum_rate:
            return False
    return report["p95_ms"] <= MAX_P95_MS


def evaluate_profile_v3(analyzer: Analyzer | None = None) -> dict[str, Any]:
    validate_acceptance_manifest()
    analyzer = analyzer or analyze_profile
    cases = rendered_case_records()
    failures = {"development": [], "acceptance": []}
    attribution = {category: [] for category in FAILURE_CATEGORIES}
    all_case_ids = [case.case_id for case in cases]
    contract_valid_ids: list[str] = []
    feedback_case_ids: list[str] = []
    feedback_passed_ids: list[str] = []
    strong_case_ids: list[str] = []
    strong_passed_ids: list[str] = []
    weak_knowledge_passed_ids: list[str] = []
    strategy_passed_ids: list[str] = []
    difficulty_passed_ids: list[str] = []
    priority_passed_ids: list[str] = []

    for case in cases:
        request, output, categories = _run_case(case, analyzer)
        if request is None or output is None:
            _append_unique(failures[_case_group(case.case_id)], case.case_id)
            _append_unique(attribution["input_preparation"], case.case_id)
            continue
        contract_valid_ids.append(case.case_id)
        actual = _actual(output)
        if case.scenario == "single_feedback_no_change":
            feedback_case_ids.append(case.case_id)
            if not output.profile_update_required:
                feedback_passed_ids.append(case.case_id)
        if _has_strong_assessment(request):
            strong_case_ids.append(case.case_id)
            if actual["profile_update_required"] == case.expected["profile_update_required"]:
                strong_passed_ids.append(case.case_id)
        if actual["weak_knowledge_ids"] == case.expected["weak_knowledge_ids"]:
            weak_knowledge_passed_ids.append(case.case_id)
        if actual["retrieval_strategy"] == case.expected["retrieval_strategy"]:
            strategy_passed_ids.append(case.case_id)
        if actual["target_difficulty"] == case.expected["target_difficulty"]:
            difficulty_passed_ids.append(case.case_id)
        if (
            actual["priority_knowledge_ids"] == case.expected["priority_knowledge_ids"]
            and actual["prerequisite_knowledge_ids"] == case.expected["prerequisite_knowledge_ids"]
        ):
            priority_passed_ids.append(case.case_id)
        if categories:
            _append_unique(failures[_case_group(case.case_id)], case.case_id)
            for category in categories:
                _append_unique(attribution[category], case.case_id)

    sample = AnalyzeProfileInput.model_validate(cases[0].payload)
    baseline = json.dumps(analyzer(sample).model_dump(mode="json"), sort_keys=True)
    timings: list[float] = []
    deterministic_passes = 0
    deterministic_failed_ids: list[str] = []
    for _ in range(DETERMINISTIC_RUNS):
        started = time.perf_counter()
        serialized = json.dumps(analyzer(sample).model_dump(mode="json"), sort_keys=True)
        timings.append((time.perf_counter() - started) * 1000)
        if serialized == baseline:
            deterministic_passes += 1
        else:
            deterministic_failed_ids.append(sample.task_id)
    timings.sort()
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "algorithm_version": ALGORITHM_VERSION,
        "config_version": AI_APP_DEV_PROFILE_V2.version,
        "seed_sha256": AI_APP_DEV_PROFILE_V2.seed_sha256,
        "case_count": len(cases),
        "development": _case_metric(30, failures["development"]),
        "acceptance": _case_metric(20, failures["acceptance"]),
        "thresholds": {"minimum_rates": MINIMUM_RATES, "maximum_p95_ms": MAX_P95_MS},
        "metrics": {
            "contract_valid_output_rate": _metric(len(cases), contract_valid_ids, all_case_ids),
            "single_subjective_feedback_no_update_rate": _metric(
                len(feedback_case_ids), feedback_passed_ids, feedback_case_ids
            ),
            "strong_evidence_update_decision_accuracy": _metric(
                len(strong_case_ids), strong_passed_ids, strong_case_ids
            ),
            "weak_knowledge_identification_accuracy": _metric(
                len(cases), weak_knowledge_passed_ids, all_case_ids
            ),
            "retrieval_strategy_accuracy": _metric(
                len(cases), strategy_passed_ids, all_case_ids
            ),
            "target_difficulty_accuracy": _metric(
                len(cases), difficulty_passed_ids, all_case_ids
            ),
            "priority_prerequisite_completeness": _metric(
                len(cases), priority_passed_ids, all_case_ids
            ),
            "deterministic_output_rate": {
                "numerator": deterministic_passes,
                "denominator": DETERMINISTIC_RUNS,
                "rate": round(deterministic_passes / DETERMINISTIC_RUNS, 4),
                "failed_case_ids": deterministic_failed_ids,
            },
        },
        "failure_attribution": attribution,
        "deterministic_runs": DETERMINISTIC_RUNS,
        "p50_ms": round(median(timings), 3),
        "p95_ms": round(_percentile(timings, 0.95), 3),
    }
    report["status"] = "passed" if _report_passes(report) else "failed"
    return report


def main() -> None:
    try:
        report = evaluate_profile_v3()
    except (ProfileFixtureError, ValidationError, ProfileAnalysisError, ValueError) as exc:
        error_code = str(exc) if isinstance(exc, ProfileFixtureError) else "evaluation_input_failed"
        print(
            json.dumps(
                {
                    "schema_version": REPORT_SCHEMA_VERSION,
                    "status": "failed",
                    "error_code": error_code,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        raise SystemExit(1) from exc
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
