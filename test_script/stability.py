from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import evaluate as evaluator
from run_live import (
    _api_json,
    _authenticate,
    _case_set_sha256,
    _classify_failure,
    _poll_task,
)


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "stability"
RESOURCE_TYPES = {"lecture", "practice_guide", "graded_quiz"}


def _assert_completed(task: dict[str, Any], run_kind: str) -> None:
    if task.get("status") != "completed" or task.get("decision") != "completed":
        raise AssertionError(
            f"{run_kind} failed: status={task.get('status')} "
            f"decision={task.get('decision')} reason={task.get('failure_reason')}"
        )
    quality = task.get("package_quality") or {}
    if quality.get("quality_rule_version") != "quality-v8-official-gates":
        raise AssertionError(f"{run_kind} did not persist V6 quality metrics")
    if not quality.get("passed"):
        raise AssertionError(f"{run_kind} package quality did not pass")
    if int(quality.get("contradicted_claim_count") or 0) != 0:
        raise AssertionError(f"{run_kind} contains contradicted claims")
    if int(quality.get("evidence_insufficient_claim_count") or 0) != 0:
        raise AssertionError(f"{run_kind} contains evidence-insufficient claims")
    if int(quality.get("unresolved_claim_count") or 0) != 0:
        raise AssertionError(f"{run_kind} contains unresolved claims")
    if float(quality.get("hallucination_rate") or 0) >= 5:
        raise AssertionError(f"{run_kind} hallucination rate did not meet the competition gate")
    if float(quality.get("difficulty_match_score") or 0) < 85:
        raise AssertionError(f"{run_kind} difficulty match did not meet the competition gate")
    if float(quality.get("core_knowledge_coverage") or 0) < 90:
        raise AssertionError(f"{run_kind} coverage did not meet the competition gate")


def _resource_map(task: dict[str, Any]) -> dict[str, dict[str, Any]]:
    resources = task.get("resources") or []
    result = {str(item.get("resource_type")): item for item in resources}
    if set(result) != RESOURCE_TYPES or len(resources) != len(RESOURCE_TYPES):
        raise AssertionError("learning package does not contain exactly three resource types")
    return result


def _assert_full_package(task: dict[str, Any]) -> dict[str, dict[str, Any]]:
    resources = _resource_map(task)
    if any(item.get("membership_type") not in {None, "generated"} for item in resources.values()):
        raise AssertionError("full generation unexpectedly inherited a resource")
    return resources


def _assert_partial_package(
    task: dict[str, Any],
    *,
    source_task_id: str,
    source_resources: dict[str, dict[str, Any]],
) -> None:
    resources = _resource_map(task)
    if task.get("source_task_id") != source_task_id:
        raise AssertionError("partial regeneration did not retain its source task")
    if task.get("trigger_type") != "resource_feedback" or task.get("event_type") != "resource_feedback":
        raise AssertionError("partial regeneration did not use the feedback branch")
    generated = {
        resource_type
        for resource_type, item in resources.items()
        if item.get("membership_type") == "generated"
    }
    inherited = {
        resource_type
        for resource_type, item in resources.items()
        if item.get("membership_type") == "inherited"
    }
    if generated != {"practice_guide"} or inherited != {"lecture", "graded_quiz"}:
        raise AssertionError("partial regeneration did not generate one and inherit two resources")
    for resource_type in inherited:
        if resources[resource_type].get("resource_id") != source_resources[resource_type].get(
            "resource_id"
        ):
            raise AssertionError(f"partial regeneration replaced inherited {resource_type}")
    if resources["practice_guide"].get("resource_id") == source_resources[
        "practice_guide"
    ].get("resource_id"):
        raise AssertionError("partial regeneration did not replace the affected practice guide")


def _result_summary(
    task: dict[str, Any], *, index: int, kind: str
) -> dict[str, Any]:
    return {
        "index": index,
        "kind": kind,
        "task_id": task.get("task_id"),
        "source_task_id": task.get("source_task_id"),
        "package_quality": task.get("package_quality") or {},
        "package_coverage": task.get("package_coverage") or {},
        "primary_owner": (task.get("package_coverage") or {}).get("primary_owner", {}),
        "resources": [
            {
                "resource_id": item.get("resource_id"),
                "resource_type": item.get("resource_type"),
                "membership_type": item.get("membership_type"),
                "review_status": item.get("review_status"),
            }
            for item in (task.get("resources") or [])
        ],
    }


def _write_report(report: dict[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    (REPORT_DIR / f"{report['run_id']}.json").write_text(payload, encoding="utf-8")
    (REPORT_DIR / "latest.json").write_text(payload, encoding="utf-8")


def _safe_agent_runs(base_url: str, task: dict[str, Any]) -> list[dict[str, Any]]:
    task_id = task.get("task_id")
    if not task_id:
        return []
    try:
        return _api_json(base_url, "GET", f"/generation-tasks/{task_id}/agent-runs")
    except Exception:
        return []


def _record_failure(
    report: dict[str, Any],
    results: list[dict[str, Any]],
    *,
    base_url: str,
    task: dict[str, Any],
    index: int,
    kind: str,
    error: Exception,
) -> None:
    results.append(
        {
            **_result_summary(task, index=index, kind=kind),
            **_classify_failure(None, task, _safe_agent_runs(base_url, task), error),
            "error": str(error)[:500],
        }
    )
    report.update(
        status="failed",
        run_count=len(results),
        finished_at=datetime.now(UTC).isoformat(),
    )
    _write_report(report)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run five full packages and five feedback-triggered partial regenerations."
    )
    parser.add_argument("--base-url", default="http://localhost:8000/api/v1")
    parser.add_argument("--timeout-seconds", type=int, default=360)
    parser.add_argument(
        "--username",
        default=os.getenv("EVALUATION_USERNAME")
        or os.getenv("INITIAL_ADMIN_USERNAME", "admin"),
    )
    parser.add_argument(
        "--password",
        default=os.getenv("EVALUATION_PASSWORD") or os.getenv("INITIAL_ADMIN_PASSWORD"),
    )
    args = parser.parse_args()
    if not args.password:
        raise SystemExit("set EVALUATION_PASSWORD or pass --password")
    _authenticate(args.base_url, args.username, args.password)
    health = _api_json(args.base_url, "GET", "/health/dependencies")
    if not health.get("ready_for_live_demo") or not (health.get("rag") or {}).get("ready"):
        raise SystemExit("backend is not ready for live stability validation")

    run_id = datetime.now(UTC).strftime("stability-%Y%m%dT%H%M%SZ")
    model_configuration = {
        "generation_model": (health.get("generation_model") or {}).get("model_name"),
        "primary_review_model": (health.get("primary_review_model") or {}).get("model_name"),
        "secondary_review_model": (health.get("secondary_review_model") or {}).get("model_name"),
        "fixture_enabled": health.get("fixture_enabled"),
    }
    rag_configuration = {
        "source_data_version": (health.get("rag") or {}).get("source_data_version"),
        "index_version": (health.get("rag") or {}).get("index_version"),
        "embedding_model": (health.get("rag") or {}).get("embedding_model"),
        "embedding_dimensions": (health.get("rag") or {}).get("embedding_dimensions"),
    }
    cases, knowledge_versions = evaluator.load_cases()
    stability_case = next(
        case for case in cases if case.get("scenario_type") == "initial_generation"
    )
    prepared = _api_json(
        args.base_url,
        "POST",
        f"/evaluations/cases/{stability_case['case_id']}/prepare",
        {},
    )
    learner_id = str(prepared["learner_id"])
    profile_id = str(prepared["profile_id"])
    full_suite_case_sha256 = _case_set_sha256(cases)
    results: list[dict[str, Any]] = []
    report = {
        "status": "running",
        "run_id": run_id,
        "quality_rule_version": "quality-v8-official-gates",
        "run_count": 0,
        "full_generation_count": 0,
        "partial_regeneration_count": 0,
        "model_configuration": model_configuration,
        "knowledge_base_versions": sorted(knowledge_versions),
        "full_suite_case_sha256": full_suite_case_sha256,
        "rag_configuration": rag_configuration,
        "started_at": datetime.now(UTC).isoformat(),
        "results": results,
    }
    _write_report(report)
    for index in range(1, 6):
        # Ten real-model tasks can outlive the demo session. Refresh the cookie
        # once per pair so authentication expiry is not misclassified as instability.
        _authenticate(args.base_url, args.username, args.password)
        full: dict[str, Any] = {}
        try:
            created = _api_json(
                args.base_url,
                "POST",
                "/generation-tasks",
                {
                    "learner_id": learner_id,
                    "profile_id": profile_id,
                    "trigger_type": "initial_generation",
                    "execution_mode": "auto",
                    "domain_code": "ai_app_dev",
                    "resource_types": ["lecture", "practice_guide", "graded_quiz"],
                    "learning_goal": f"V6 稳定性验证第 {index} 轮完整学习包",
                },
            )
            full = {"task_id": created.get("task_id")}
            full = _poll_task(args.base_url, str(created["task_id"]), args.timeout_seconds)
            _assert_completed(full, "full_generation")
            full_resources = _assert_full_package(full)
        except Exception as exc:
            _record_failure(
                report,
                results,
                base_url=args.base_url,
                task=full,
                index=index,
                kind="full_generation",
                error=exc,
            )
            raise
        results.append(_result_summary(full, index=index, kind="full_generation"))
        report.update(
            run_count=len(results),
            full_generation_count=index,
            updated_at=datetime.now(UTC).isoformat(),
        )
        _write_report(report)
        practice = full_resources["practice_guide"]
        partial: dict[str, Any] = {}
        try:
            _authenticate(args.base_url, args.username, args.password)
            feedback = _api_json(
                args.base_url,
                "POST",
                f"/resources/{practice['resource_id']}/feedback",
                {
                    "learner_id": learner_id,
                    "feedback_type": "incorrect",
                    "selected_text": "稳定性复核：请重新检索并局部修订此资源。",
                },
            )
            partial = {"task_id": feedback.get("task_id")}
            partial = _poll_task(
                args.base_url, str(feedback["task_id"]), args.timeout_seconds
            )
            _assert_completed(partial, "partial_regeneration")
            _assert_partial_package(
                partial,
                source_task_id=str(full["task_id"]),
                source_resources=full_resources,
            )
        except Exception as exc:
            _record_failure(
                report,
                results,
                base_url=args.base_url,
                task=partial,
                index=index,
                kind="partial_regeneration",
                error=exc,
            )
            report.update(
                partial_regeneration_count=index - 1,
            )
            _write_report(report)
            raise
        results.append(_result_summary(partial, index=index, kind="partial_regeneration"))
        report.update(
            run_count=len(results),
            partial_regeneration_count=index,
            updated_at=datetime.now(UTC).isoformat(),
        )
        _write_report(report)
        print(f"[{index}/5] full + partial passed", flush=True)

    report.update(
        status="passed",
        run_count=len(results),
        full_generation_count=5,
        partial_regeneration_count=5,
        evaluated_at=datetime.now(UTC).isoformat(),
        finished_at=datetime.now(UTC).isoformat(),
    )
    _write_report(report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
