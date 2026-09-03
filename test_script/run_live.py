from __future__ import annotations

import argparse
import hashlib
import os
import json
import re
import time
from http.cookiejar import CookieJar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener

import evaluate as evaluator


ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "reports" / "evaluation" / "runs"
STAGE_LIMITS = {"smoke": 6, "regression": 15, "formal": 50}
PRIOR_STAGE = {"regression": "smoke", "formal": "regression"}
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
RUN_ID_RE = re.compile(r"live-(?:smoke|regression|formal)-\d{8}T\d{6}Z")
KNOWLEDGE_ITEMS_PATH = ROOT / "data" / "seed" / "knowledge_items.json"
FAILURE_CATEGORIES = {
    "program_defect",
    "knowledge_data_gap",
    "case_defect",
    "external_service_failure",
    "operations_failure",
}


class ApiFailure(RuntimeError):
    pass


COOKIE_JAR = CookieJar()
HTTP_OPENER = build_opener(HTTPCookieProcessor(COOKIE_JAR))


def _csrf_token() -> str | None:
    return next((cookie.value for cookie in COOKIE_JAR if cookie.name == "csrf_token"), None)


def _api_json(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 30,
) -> Any:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if csrf := _csrf_token():
        headers["X-CSRF-Token"] = csrf
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        method=method,
        headers=headers,
    )
    try:
        with HTTP_OPENER.open(request, timeout=timeout) as response:
            envelope = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ApiFailure(f"{method} {path} returned {exc.code}: {detail[:500]}") from exc
    except (URLError, TimeoutError) as exc:
        raise ApiFailure(f"{method} {path} failed: {exc}") from exc
    if envelope.get("error"):
        raise ApiFailure(f"{method} {path} returned API error: {envelope['error']}")
    return envelope.get("data")


def _authenticate(base_url: str, username: str, password: str) -> None:
    _api_json(
        base_url,
        "POST",
        "/auth/login",
        {"username": username, "password": password},
    )
    if not _csrf_token():
        raise ApiFailure("login did not establish the CSRF cookie")


def _case_set_sha256(cases: list[dict[str, Any]]) -> str:
    canonical_cases = json.dumps(
        cases,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical_cases).hexdigest()


def _prior_stage_exists(
    stage: str,
    *,
    full_suite_case_sha256: str,
    model_configuration: dict[str, Any],
    knowledge_base_versions: list[str],
    rag_configuration: dict[str, Any],
) -> bool:
    required = PRIOR_STAGE.get(stage)
    if required is None:
        return True
    for path in RUN_DIR.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if (
                payload.get("stage") == required
                and payload.get("valid") is True
                and not payload.get("diagnostic_case_id")
                and (payload.get("stage_acceptance") or {}).get("accepted") is True
                and payload.get("full_suite_case_sha256") == full_suite_case_sha256
                and payload.get("model_configuration") == model_configuration
                and payload.get("knowledge_base_versions") == knowledge_base_versions
                and payload.get("rag_configuration") == rag_configuration
            ):
                return True
        except (OSError, json.JSONDecodeError):
            continue
    return False


def _write_run_checkpoint(path: Path, run: dict[str, Any]) -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")


def _checkpoint_result_reusable(item: dict[str, Any]) -> bool:
    observed = item.get("observed_result") or {}
    return bool(observed.get("determinable")) and observed.get(
        "failure_category"
    ) != "program_defect"


def _resume_run(
    run_id: str,
    *,
    stage: str,
    diagnostic_case_id: str | None,
    selected_case_ids: set[str],
    model_configuration: dict[str, Any],
    knowledge_base_versions: list[str],
    rag_configuration: dict[str, Any],
    case_set_sha256: str,
    full_suite_case_sha256: str,
) -> tuple[Path, dict[str, Any]]:
    if not RUN_ID_RE.fullmatch(run_id):
        raise SystemExit("invalid --resume-run-id")
    path = RUN_DIR / f"{run_id}.json"
    if not path.is_file():
        raise SystemExit(f"resume run does not exist: {run_id}")
    try:
        run = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"resume run is unreadable: {run_id}") from exc
    expected = {
        "run_id": run_id,
        "run_mode": "live",
        "stage": stage,
        "diagnostic_case_id": diagnostic_case_id,
        "model_configuration": model_configuration,
        "knowledge_base_versions": knowledge_base_versions,
        "rag_configuration": rag_configuration,
        "case_set_sha256": case_set_sha256,
        "full_suite_case_sha256": full_suite_case_sha256,
    }
    mismatched = [key for key, value in expected.items() if run.get(key) != value]
    if mismatched:
        raise SystemExit(
            "resume run configuration mismatch: " + ", ".join(sorted(mismatched))
        )
    result_ids = [str(item.get("case_id")) for item in run.get("results", [])]
    if len(result_ids) != len(set(result_ids)) or not set(result_ids).issubset(
        selected_case_ids
    ):
        raise SystemExit("resume run contains duplicate or out-of-scope cases")
    determinable_ids = {
        str(item.get("case_id"))
        for item in run.get("results", [])
        if _checkpoint_result_reusable(item)
    }
    if run.get("complete") is True and selected_case_ids.issubset(determinable_ids):
        raise SystemExit("resume run is already complete")
    # A stage can finish mechanically while retaining indeterminable cases.
    # Reopen only those observations for checkpoint recovery.
    run["complete"] = False
    run["valid"] = False
    run.pop("stage_acceptance", None)
    return path, run


def _stage_acceptance(summary: dict[str, Any], expected_case_count: int) -> dict[str, Any]:
    """Evaluate a live stage against competition gates and retain review diagnostics."""
    metrics = summary.get("metrics") or {}
    competition_checks = {
        "all_cases_present": int(summary.get("case_count") or 0) == expected_case_count,
        "all_cases_determinable": int(summary.get("evaluated_case_count") or 0)
        == expected_case_count,
        "hallucination_rate_below_5_percent": (
            (metrics.get("hallucination_rate") or {}).get("ratio") is not None
            and float((metrics.get("hallucination_rate") or {})["ratio"]) < 0.05
        ),
        "difficulty_match_at_least_85_percent": (
            (metrics.get("difficulty_match_accuracy") or {}).get("ratio") is not None
            and float((metrics.get("difficulty_match_accuracy") or {})["ratio"]) >= 0.85
        ),
        "core_coverage_at_least_90_percent": (
            (metrics.get("core_knowledge_coverage") or {}).get("ratio") is not None
            and float((metrics.get("core_knowledge_coverage") or {})["ratio"]) >= 0.90
        ),
    }
    diagnostic_checks = {
        "no_evidence_insufficient": int(
            (metrics.get("evidence_insufficient_claims") or {}).get("count") or 0
        )
        == 0,
        "no_unresolved_claims": int(
            (metrics.get("unresolved_claims") or {}).get("count") or 0
        )
        == 0,
        "review_decisions_match": (
            (metrics.get("review_decision_accuracy") or {}).get("ratio") == 1.0
        ),
        "profile_decisions_match": (
            (metrics.get("profile_decision_accuracy") or {}).get("ratio") == 1.0
        ),
    }
    checks = {**competition_checks, **diagnostic_checks}
    return {
        "accepted": all(competition_checks.values()),
        "expected_case_count": expected_case_count,
        "competition_checks": competition_checks,
        "diagnostic_checks": diagnostic_checks,
        # Retain the flattened view for consumers of earlier V6 reports.
        "checks": checks,
        "failed_checks": [
            name for name, passed in competition_checks.items() if not passed
        ],
        "diagnostic_findings": [
            name for name, passed in diagnostic_checks.items() if not passed
        ],
    }


def _poll_task(base_url: str, task_id: str, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        task = _api_json(base_url, "GET", f"/generation-tasks/{task_id}")
        if task.get("status") in TERMINAL_STATUSES:
            return task
        time.sleep(1)
    raise ApiFailure(f"task {task_id} did not finish within {timeout_seconds}s")


def _final_review(runs: list[dict[str, Any]], resource_type: str) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for run in runs:
        if (run.get("input_summary") or {}).get("step") != "review_resource":
            continue
        for report in (run.get("output_summary") or {}).get("resource_reviews", []):
            if report.get("resource_type") == resource_type:
                candidates.append(report)
    return candidates[-1] if candidates else {}


def _review_channels(report: dict[str, Any]) -> list[dict[str, Any]]:
    arbitration = report.get("arbitration") or {}
    if arbitration.get("primary_recheck") and arbitration.get("secondary_recheck"):
        return [arbitration["primary_recheck"], arbitration["secondary_recheck"]]
    return [report.get("primary_review") or {}, report.get("secondary_review") or {}]


def _model_calls(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        call
        for run in runs
        for call in (run.get("output_summary") or {}).get("model_calls", [])
        if isinstance(call, dict)
    ]


def _knowledge_ids_from_source_refs(source_ref_ids: set[str]) -> set[str]:
    """Resolve V2 retrieval source references without inspecting resource text."""
    return {
        source_ref_id.split("::", 1)[0]
        for source_ref_id in source_ref_ids
        if source_ref_id
    }


def _profile_decision(runs: list[dict[str, Any]]) -> str:
    analyses = [
        run.get("output_summary") or {}
        for run in runs
        if (run.get("input_summary") or {}).get("step") == "analyze_profile"
    ]
    if not analyses:
        return "not_evaluated"
    return "update_profile" if any(item.get("profile_update_required") for item in analyses) else "no_change"


def _knowledge_capabilities() -> dict[str, set[str]]:
    items = json.loads(KNOWLEDGE_ITEMS_PATH.read_text(encoding="utf-8"))
    return {
        str(item["knowledge_id"]): {
            str(capability) for capability in item.get("evidence_capabilities", [])
        }
        for item in items
    }


def _case_evidence_diagnosis(case: dict[str, Any] | None) -> dict[str, Any]:
    if not case:
        return {"valid": True, "missing_knowledge_ids": [], "missing_capability_ids": []}
    target_ids = [str(item) for item in case.get("target_core_knowledge_ids", [])]
    gold = case.get("gold_standard") or {}
    required_source_ids = [str(item) for item in gold.get("required_source_ids", [])]
    capability = str(gold.get("required_evidence_capability") or "concept")
    structural_errors: list[str] = []
    if not target_ids:
        structural_errors.append("target_core_knowledge_ids_empty")
    if set(required_source_ids) != set(target_ids):
        structural_errors.append("required_sources_do_not_match_targets")
    if case.get("resource_type") == "practice_guide" and capability != "operation":
        structural_errors.append("practice_guide_requires_operation_evidence")
    capabilities = _knowledge_capabilities()
    missing_ids = [item for item in target_ids if item not in capabilities]
    missing_capability_ids = [
        item
        for item in target_ids
        if item in capabilities and capability not in capabilities[item]
    ]
    return {
        "valid": not structural_errors and not missing_ids,
        "structural_errors": structural_errors,
        "missing_knowledge_ids": missing_ids,
        "missing_capability_ids": missing_capability_ids,
        "required_evidence_capability": capability,
    }


def _validate_case_evidence(cases: list[dict[str, Any]]) -> None:
    case_defects: list[str] = []
    knowledge_gaps: list[str] = []
    for case in cases:
        diagnosis = _case_evidence_diagnosis(case)
        case_id = str(case.get("case_id"))
        if not diagnosis["valid"]:
            case_defects.append(case_id)
        elif diagnosis["missing_capability_ids"]:
            knowledge_gaps.append(case_id)
    if case_defects:
        raise ValueError("case_defect:" + ",".join(case_defects))
    if knowledge_gaps:
        raise ValueError("knowledge_data_gap:" + ",".join(knowledge_gaps))


def _failure_signal(
    task: dict[str, Any], runs: list[dict[str, Any]], error: Exception | str | None
) -> dict[str, Any]:
    failed_runs = [item for item in runs if item.get("status") == "failed"]
    latest = failed_runs[-1] if failed_runs else {}
    output = latest.get("output_summary") or {}
    details = task.get("failure_details") or {}
    code = str(
        task.get("failure_reason")
        or output.get("failure_code")
        or (error if error is not None else "quality_gate_failed")
    )[:200]
    return {
        "failure_code": code,
        "failed_step": output.get("failed_step") or details.get("failed_step"),
        "field_paths": list(output.get("field_paths") or details.get("field_paths") or [])[:20],
    }


def _classify_failure(
    case: dict[str, Any] | None,
    task: dict[str, Any] | None,
    runs: list[dict[str, Any]] | None,
    error: Exception | str | None = None,
) -> dict[str, Any]:
    """Classify a failed run from persisted evidence, never from evidence_gap alone."""
    task = task or {}
    runs = runs or []
    signal = _failure_signal(task, runs, error)
    code = signal["failure_code"].lower()
    case_diagnosis = _case_evidence_diagnosis(case)

    if not case_diagnosis["valid"]:
        category = "case_defect"
        basis = "评测目标不存在或案例结构违反版本化案例合同。"
        confidence = "high"
    elif "evidence_gap" in code or "revision_exhausted" in code or "resource_rejected" in code:
        if case_diagnosis["missing_capability_ids"]:
            category = "knowledge_data_gap"
            basis = "案例有效，但本地知识数据缺少案例要求的证据能力。"
            confidence = "high"
        elif "evidence_gap" in code:
            category = "program_defect"
            basis = "案例和知识证据能力均有效，证据预检或检索仍报告缺口。"
            confidence = "high"
        else:
            category = "external_service_failure"
            basis = "案例和知识证据充分，但真实模型在两轮局部修订后仍未通过审核。"
            confidence = "medium"
    elif any(
        marker in code
        for marker in (
            "model_call_failed",
            "structured_output_invalid",
            "structure_validation_failed",
            "patch_validation_failed",
            "provider",
            "rate limit",
            "timeout",
            "timed out",
        )
    ):
        category = "external_service_failure"
        basis = "外部模型调用或结构化输出在恢复预算耗尽后失败。"
        confidence = "high"
    elif any(
        marker in code
        for marker in (
            "candidate_index_stale",
            "rag_not_ready",
            "persistence_interrupted",
            "checkpoint_",
            "connection refused",
            "csrf",
            "returned 401",
            "returned 403",
            "returned 503",
        )
    ):
        category = "operations_failure"
        basis = "索引、检查点、持久化、会话或运行环境未处于可验收状态。"
        confidence = "high"
    elif "returned 422" in code or "evaluation_case_" in code:
        category = "case_defect"
        basis = "评测请求或版本化案例合同无效。"
        confidence = "medium"
    else:
        category = "program_defect"
        basis = "已排除已知案例、知识、模型服务和运维信号，保留为程序路径缺陷。"
        confidence = "low"

    assert category in FAILURE_CATEGORIES
    return {
        **signal,
        "failure_category": category,
        "classification_basis": basis,
        "classification_confidence": confidence,
        "case_evidence_diagnosis": case_diagnosis,
    }


def _observed_result(
    case: dict[str, Any],
    task: dict[str, Any],
    runs: list[dict[str, Any]],
    elapsed_ms: int,
) -> dict[str, Any]:
    task_decision = str(task.get("decision") or "")
    if task.get("status") == "completed" and task_decision == "no_change":
        model_calls = _model_calls(runs)
        agent_latency: dict[str, int] = {}
        for run in runs:
            step = str((run.get("input_summary") or {}).get("step") or "")
            if step:
                agent_latency[step] = agent_latency.get(step, 0) + int(
                    run.get("duration_ms") or 0
                )
        return {
            "evaluated_claim_count": 0,
            "contradicted_claim_count": 0,
            "evidence_insufficient_claim_count": 0,
            "unresolved_claim_count": 0,
            "generated_fact_count": 0,
            "hallucinated_fact_count": 0,
            # No new resource exists, so resource difficulty is not applicable.
            "difficulty_matched": None,
            "covered_core_knowledge_count": 0,
            "target_core_knowledge_count": 0,
            "review_conclusion": "no_change",
            "profile_decision": _profile_decision(runs),
            "latency_ms": elapsed_ms,
            "agent_latency_ms": agent_latency,
            "determinable": True,
            "unable_to_determine": [],
            "provider_mode": "not_applicable",
            "model_calls": model_calls,
            "failure_category": None,
            "failure_code": None,
            "classification_basis": None,
            "classification_confidence": None,
            "field_paths": [],
        }
    report = _final_review(runs, str(case["resource_type"]))
    model_calls = _model_calls(runs)
    all_live = bool(model_calls) and all(
        call.get("provider_mode") == "live" for call in model_calls
    )
    review_channels = _review_channels(report)
    certified_question_bank = (
        str(case.get("resource_type")) == "graded_quiz"
        and len(review_channels) == 2
        and all(
            channel.get("model_name") == "deterministic-certified-question-validator"
            and channel.get("passed") is True
            for channel in review_channels
        )
    )
    execution_evidence_valid = all_live or certified_question_bank
    quality = report.get("quality_metrics") or {}
    resource = next(
        (
            item
            for item in task.get("resources", [])
            if item.get("resource_type") == case.get("resource_type")
        ),
        {},
    )
    decision = str(report.get("decision") or task.get("decision") or "failed")
    conclusion = {"rejected": "failed", "completed": "passed", "passed": "passed"}.get(
        decision, decision
    )
    agent_latency: dict[str, int] = {}
    for run in runs:
        step = str((run.get("input_summary") or {}).get("step") or "")
        if not step:
            continue
        agent_latency[step] = agent_latency.get(step, 0) + int(run.get("duration_ms") or 0)

    evaluated_claim_count = int(
        quality.get("evaluated_claim_count", quality.get("verifiable_claim_count", 0))
    )
    evidence_insufficient_count = int(quality.get("evidence_insufficient_claim_count", 0))
    unresolved_count = int(quality.get("unresolved_claim_count", 0))
    determinable = bool(report and evaluated_claim_count > 0 and execution_evidence_valid)
    result = {
        "evaluated_claim_count": evaluated_claim_count,
        "contradicted_claim_count": int(quality.get("contradicted_claim_count", 0)),
        "evidence_insufficient_claim_count": evidence_insufficient_count,
        "unresolved_claim_count": unresolved_count,
        "generated_fact_count": evaluated_claim_count,
        "hallucinated_fact_count": int(quality.get("hallucinated_claim_count", 0)),
        "difficulty_matched": bool(
            resource.get("difficulty") == case.get("target_difficulty")
            and float(quality.get("difficulty_match_score", 0)) >= 85
        ),
        "covered_core_knowledge_count": int(quality.get("covered_core_knowledge_count", 0)),
        "target_core_knowledge_count": int(quality.get("target_core_knowledge_count", 0)),
        "review_conclusion": conclusion,
        "profile_decision": _profile_decision(runs),
        "latency_ms": elapsed_ms,
        "agent_latency_ms": agent_latency,
        "determinable": determinable,
        "unable_to_determine": [],
        "provider_mode": (
            "live"
            if all_live
            else "deterministic_certified_question_bank"
            if certified_question_bank
            else "invalid"
        ),
        "model_calls": [
            {
                "model_name": call.get("model_name"),
                "role": call.get("role"),
                "duration_ms": call.get("duration_ms"),
                "tokens_input": call.get("tokens_input"),
                "tokens_output": call.get("tokens_output"),
            }
            for call in model_calls
        ],
    }
    if not determinable or task.get("status") != "completed" or decision not in {
        "completed",
        "passed",
    }:
        result.update(_classify_failure(case, task, runs))
    else:
        result.update(
            {
                "failure_category": None,
                "failure_code": None,
                "classification_basis": None,
                "classification_confidence": None,
                "field_paths": [],
            }
        )
    return result


def _case_goal(case: dict[str, Any]) -> str:
    return (
        f"V4 评测案例 {case['case_id']}，目标知识点："
        + "、".join(case.get("target_core_knowledge_ids", []))
    )


def _create_case_task(
    base_url: str,
    case: dict[str, Any],
    *,
    learner_id: str,
    profile_id: str,
    timeout_seconds: int,
    full_package: bool,
) -> tuple[str, dict[str, Any], int]:
    resource_types = (
        ["lecture", "practice_guide", "graded_quiz"]
        if full_package
        else [case["resource_type"]]
    )
    payload = {
        "learner_id": learner_id,
        "profile_id": profile_id,
        "trigger_type": "initial_generation",
        "execution_mode": "auto",
        "domain_code": "ai_app_dev",
        "resource_types": resource_types,
        "learning_goal": _case_goal(case),
    }
    request_started = time.perf_counter()
    created = _api_json(base_url, "POST", "/generation-tasks", payload)
    trigger_response_ms = round((time.perf_counter() - request_started) * 1000)
    task_id = str(created["task_id"])
    return task_id, _poll_task(base_url, task_id, timeout_seconds), trigger_response_ms


def _published_resource(task: dict[str, Any], resource_type: str) -> dict[str, Any]:
    if task.get("status") != "completed":
        raise ApiFailure(
            f"baseline task {task.get('task_id')} failed: {task.get('failure_reason')}"
        )
    resource = next(
        (
            item
            for item in task.get("resources", [])
            if item.get("resource_type") == resource_type
            and item.get("review_status") == "passed"
        ),
        None,
    )
    if resource is None:
        raise ApiFailure(f"baseline task did not publish {resource_type}")
    return resource


def run_case(base_url: str, case: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    prepared = _api_json(
        base_url, "POST", f"/evaluations/cases/{case['case_id']}/prepare", {}
    )
    learner_id = str(prepared["learner_id"])
    profile_id = str(prepared["profile_id"])
    scenario_type = str(case.get("scenario_type") or "initial_generation")
    started = time.perf_counter()
    baseline_task_id: str | None = None
    trigger_response_ms: int | None = None
    if scenario_type == "initial_generation":
        task_id, task, trigger_response_ms = _create_case_task(
            base_url,
            case,
            learner_id=learner_id,
            profile_id=profile_id,
            timeout_seconds=timeout_seconds,
            full_package=False,
        )
    elif scenario_type in {"feedback_revision", "challenge_task"}:
        baseline_task_id, baseline, _baseline_response_ms = _create_case_task(
            base_url,
            case,
            learner_id=learner_id,
            profile_id=profile_id,
            timeout_seconds=timeout_seconds,
            # The case evaluates feedback on one resource. Requiring an unrelated
            # three-resource package here can make a valid conceptual lecture or
            # quiz fail the practice-guide evidence preflight before feedback is
            # even exercised. Package inheritance is covered by stability.py.
            full_package=False,
        )
        resource = _published_resource(baseline, str(case["resource_type"]))
        resource_id = str(resource["resource_id"])
        if scenario_type == "feedback_revision":
            request_started = time.perf_counter()
            feedback = _api_json(
                base_url,
                "POST",
                f"/resources/{resource_id}/feedback",
                {
                    "learner_id": learner_id,
                    "feedback_type": "incorrect",
                    "selected_text": "评测复核：该处事实需要重新检索证据并局部修订。",
                },
            )
            trigger_response_ms = round((time.perf_counter() - request_started) * 1000)
            if feedback.get("recommended_action") != "review" or not feedback.get("task_id"):
                raise ApiFailure("feedback case did not create a review task")
            task_id = str(feedback["task_id"])
        else:
            session = _api_json(
                base_url,
                "POST",
                "/tutoring/sessions",
                {"learner_id": learner_id, "resource_id": resource_id},
            )
            request_started = time.perf_counter()
            challenge = _api_json(
                base_url,
                "POST",
                f"/tutoring/sessions/{session['session_id']}/messages",
                {
                    "content": "这部分太简单了，我已经掌握，请生成更难的迁移挑战。",
                    "evidence": [
                        {
                            "evidence_id": f"{case['case_id']}-validated-mastery",
                            "evidence_type": "validated_behavior",
                            "summary": "版本化评测案例提供的已确认迁移任务完成行为",
                            "knowledge_id": str(case["target_core_knowledge_ids"][0]),
                            "confidence": 0.9,
                            "confirmed": True,
                        }
                    ],
                },
                timeout=timeout_seconds,
            )
            trigger_response_ms = round((time.perf_counter() - request_started) * 1000)
            if challenge.get("recommended_action") != "challenge":
                raise ApiFailure("challenge case did not create a challenge task")
            if challenge.get("task_id"):
                task_id = str(challenge["task_id"])
            elif challenge.get("feedback_id"):
                request_started = time.perf_counter()
                confirmed = _api_json(
                    base_url,
                    "POST",
                    f"/generation-tasks/feedback/{challenge['feedback_id']}/confirm",
                )
                trigger_response_ms = round((time.perf_counter() - request_started) * 1000)
                task_id = str(confirmed["task_id"])
            else:
                raise ApiFailure("challenge recommendation did not expose confirmation id")
        task = _poll_task(base_url, task_id, timeout_seconds)
    else:
        raise ApiFailure(f"unsupported evaluation scenario: {scenario_type}")
    runs = _api_json(base_url, "GET", f"/generation-tasks/{task_id}/agent-runs")
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    return {
        "case_id": case["case_id"],
        "scenario_type": scenario_type,
        "baseline_task_id": baseline_task_id,
        "task_id": task_id,
        "task_status": task.get("status"),
        "observed_result": {
            **_observed_result(case, task, runs, elapsed_ms),
            "trigger_response_ms": trigger_response_ms,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run real-model evaluation through the public API.")
    parser.add_argument("--stage", choices=tuple(STAGE_LIMITS), required=True)
    parser.add_argument("--case-id", help="Run one named case for live diagnostics; not stage acceptance.")
    parser.add_argument(
        "--resume-run-id",
        help="Resume an incomplete run checkpoint created by this script.",
    )
    parser.add_argument("--base-url", default="http://localhost:8000/api/v1")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument(
        "--username",
        default=os.getenv("EVALUATION_USERNAME")
        or os.getenv("INITIAL_ADMIN_USERNAME", "admin"),
    )
    parser.add_argument(
        "--password",
        default=os.getenv("EVALUATION_PASSWORD") or os.getenv("INITIAL_ADMIN_PASSWORD"),
    )
    parser.add_argument("--xlsx", action="store_true")
    args = parser.parse_args()

    if not args.password:
        raise SystemExit("set EVALUATION_PASSWORD or pass --password")
    _authenticate(args.base_url, args.username, args.password)
    health = _api_json(args.base_url, "GET", "/health/dependencies")
    if not health.get("ready_for_live_demo") or not (health.get("rag") or {}).get("ready"):
        raise SystemExit("backend is not ready for live demo; check model configuration and fixture mode")
    if not health.get("evaluation_runner_enabled"):
        raise SystemExit(
            "backend evaluation runner is disabled; set "
            "ENABLE_EVALUATION_RUNNER=true for versioned live evaluation"
        )

    cases, versions = evaluator.load_cases()
    _validate_case_evidence(cases)
    selected = cases[: STAGE_LIMITS[args.stage]]
    if args.case_id:
        selected = [case for case in cases if case.get("case_id") == args.case_id]
        if not selected:
            raise SystemExit(f"unknown evaluation case: {args.case_id}")
    case_set_sha256 = _case_set_sha256(selected)
    full_suite_case_sha256 = _case_set_sha256(cases)
    model_configuration = {
        "generation_model": health.get("generation_model", {}).get("model_name"),
        "primary_review_model": health.get("primary_review_model", {}).get("model_name"),
        "secondary_review_model": health.get("secondary_review_model", {}).get("model_name"),
        "fixture_enabled": health.get("fixture_enabled"),
        "evaluation_overrides_enabled": health.get("evaluation_overrides_enabled"),
        "evaluation_runner_enabled": health.get("evaluation_runner_enabled"),
    }
    knowledge_base_versions = sorted(versions)
    rag_configuration = {
        "source_data_version": (health.get("rag") or {}).get("source_data_version"),
        "index_version": (health.get("rag") or {}).get("index_version"),
        "embedding_model": (health.get("rag") or {}).get("embedding_model"),
        "embedding_dimensions": (health.get("rag") or {}).get("embedding_dimensions"),
    }
    if not args.case_id and not _prior_stage_exists(
        args.stage,
        full_suite_case_sha256=full_suite_case_sha256,
        model_configuration=model_configuration,
        knowledge_base_versions=knowledge_base_versions,
        rag_configuration=rag_configuration,
    ):
        raise SystemExit(
            f"run {PRIOR_STAGE[args.stage]} stage successfully with the current "
            f"case suite, models, knowledge base, and RAG index before {args.stage}"
        )
    if args.resume_run_id:
        run_path, run = _resume_run(
            args.resume_run_id,
            stage=args.stage,
            diagnostic_case_id=args.case_id,
            selected_case_ids={str(case["case_id"]) for case in selected},
            model_configuration=model_configuration,
            knowledge_base_versions=knowledge_base_versions,
            rag_configuration=rag_configuration,
            case_set_sha256=case_set_sha256,
            full_suite_case_sha256=full_suite_case_sha256,
        )
        run_id = args.resume_run_id
        results = list(run.get("results", []))
    else:
        run_id = datetime.now(UTC).strftime(f"live-{args.stage}-%Y%m%dT%H%M%SZ")
        run_path = RUN_DIR / f"{run_id}.json"
        results: list[dict[str, Any]] = []
        run = {
            "run_id": run_id,
            "run_mode": "live",
            "stage": args.stage,
            "case_count": 0,
            "diagnostic_case_id": args.case_id,
            "valid": False,
            "complete": False,
            "model_configuration": model_configuration,
            "knowledge_base_versions": knowledge_base_versions,
            "rag_configuration": rag_configuration,
            "case_set_sha256": case_set_sha256,
            "full_suite_case_sha256": full_suite_case_sha256,
            "started_at": datetime.now(UTC).isoformat(),
            "results": results,
        }
        _write_run_checkpoint(run_path, run)
    completed_case_ids = {
        str(item.get("case_id"))
        for item in results
        if _checkpoint_result_reusable(item)
    }
    for case in selected:
        if str(case["case_id"]) in completed_case_ids:
            print(f"[{len(results)}/{len(selected)}] {case['case_id']} (checkpoint)", flush=True)
            continue
        # A resumed run replaces an earlier indeterminable observation for the
        # same case instead of creating duplicate results.
        results[:] = [
            item for item in results if str(item.get("case_id")) != str(case["case_id"])
        ]
        try:
            # A real-model stage can outlive the demo session TTL. Refresh the
            # Cookie session before every case so authentication expiry is not
            # misreported as an indeterminable quality result.
            _authenticate(args.base_url, args.username, args.password)
            results.append(run_case(args.base_url, case, args.timeout_seconds))
        except Exception as exc:
            failure = _classify_failure(case, {}, [], exc)
            results.append(
                {
                    "case_id": case["case_id"],
                    "error": str(exc)[:500],
                    "observed_result": {
                        "determinable": False,
                        "unable_to_determine": [str(exc)[:500]],
                        **failure,
                    },
                }
            )
        run["case_count"] = len(results)
        run["results"] = results
        run["updated_at"] = datetime.now(UTC).isoformat()
        _write_run_checkpoint(run_path, run)
        print(f"[{len(results)}/{len(selected)}] {case['case_id']}", flush=True)

    valid = not any(
        not item.get("observed_result", {}).get("determinable") for item in results
    )
    run["case_count"] = len(results)
    run["valid"] = valid
    run["complete"] = True
    run["finished_at"] = datetime.now(UTC).isoformat()
    merged = evaluator.merge_live_results(cases, run)
    summary = evaluator.evaluate(merged, versions, run_mode="live", run_metadata=run)
    if args.case_id:
        run["stage_acceptance"] = {
            "accepted": False,
            "diagnostic_only": True,
            "failed_checks": ["diagnostic_case_is_not_a_stage"],
        }
    else:
        run["stage_acceptance"] = _stage_acceptance(summary, STAGE_LIMITS[args.stage])
    summary["stage_acceptance"] = run["stage_acceptance"]
    _write_run_checkpoint(run_path, run)
    evaluator.write_reports(summary, xlsx=args.xlsx)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if not valid or (
        not args.case_id and not bool(run["stage_acceptance"].get("accepted"))
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
