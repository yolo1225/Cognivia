"""Run three live, privacy-preserving smart-manufacturing submission cases.

This is deliberately a demo-data acceptance runner, not a 50-case quality evaluation.
It exercises the production API and records only the identifiers and summaries required
by the competition test-data requirement.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from run_live import _api_json, _authenticate, _poll_task


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "data" / "submission_fixtures" / "smart_manufacturing_v1"
CASE_PATH = FIXTURE_DIR / "manual_demo_cases.json"
REPORT_PATH = ROOT / "reports" / "demo" / "smart-manufacturing-latest.json"
DELIVERABLE_DIR = ROOT / "deliverables" / "smart_manufacturing-test-data"
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
EXPECTED_TYPES = {"lecture", "practice_guide", "graded_quiz"}


def _safe_error(exc: Exception) -> str:
    return " ".join(str(exc).split())[:500] or type(exc).__name__


def _load_cases() -> list[dict[str, Any]]:
    payload = json.loads(CASE_PATH.read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if (
        not isinstance(cases, list)
        or payload.get("domain_code") != "smart_manufacturing"
        or {case.get("profile_type") for case in cases} != {"beginner", "intermediate", "advanced"}
    ):
        raise ValueError("smart manufacturing manual demo cases are invalid")
    return cases


def _live_runs(base_url: str, task_id: str) -> list[dict[str, Any]]:
    runs = _api_json(base_url, "GET", f"/generation-tasks/{task_id}/agent-runs")
    model_runs = [run for run in runs if run.get("model_name")]
    if not model_runs:
        raise AssertionError(f"task {task_id} has no model run evidence")
    if any((run.get("output_summary") or {}).get("provider_mode") != "live" for run in model_runs):
        raise AssertionError(f"task {task_id} contains a non-live model run")
    return runs


def _run_step(run: dict[str, Any]) -> str:
    return str((run.get("input_summary") or {}).get("step") or "unknown")


def _run_summary(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "step": _run_step(run),
            "status": run.get("status"),
            "model_name": run.get("model_name"),
            "duration_ms": run.get("duration_ms"),
        }
        for run in runs
    ]


def _review_roles(runs: list[dict[str, Any]]) -> list[str]:
    return sorted(
        {
            str(call["role"])
            for run in runs
            if _run_step(run) == "review_resource"
            for call in ((run.get("output_summary") or {}).get("model_calls") or [])
            if isinstance(call, dict) and call.get("role")
        }
    )


def _resource_summary(base_url: str, task_id: str, *, expect_full_package: bool) -> list[dict[str, Any]]:
    resources = _api_json(base_url, "GET", f"/resources?task_id={task_id}")
    resource_types = {str(resource.get("resource_type")) for resource in resources}
    if expect_full_package and resource_types != EXPECTED_TYPES:
        raise AssertionError(f"task {task_id} did not publish all three resource types: {resource_types}")
    if not resources:
        raise AssertionError(f"task {task_id} has no published resource")

    result = []
    for resource in resources:
        if resource.get("review_status") != "passed":
            raise AssertionError(f"resource {resource.get('resource_id')} was not passed")
        if not resource.get("sources") or not resource.get("source_details"):
            raise AssertionError(f"resource {resource.get('resource_id')} has no source reference")
        if not resource.get("difficulty") or not resource.get("quality_metrics"):
            raise AssertionError(f"resource {resource.get('resource_id')} lacks quality metadata")
        export = _api_json(
            base_url,
            "POST",
            f"/resources/{resource['resource_id']}/export",
            {"format": "markdown", "audience": "learner"},
        )
        source_ids = sorted(
            {
                str(source.get("knowledge_id"))
                for source in resource.get("source_details") or []
                if isinstance(source, dict) and source.get("knowledge_id")
            }
        )
        result.append(
            {
                "resource_id": resource["resource_id"],
                "resource_type": resource["resource_type"],
                "difficulty": resource["difficulty"],
                "review_status": resource["review_status"],
                "source_knowledge_ids": source_ids,
                "quality_metrics": resource["quality_metrics"],
                "export": {
                    key: export.get(key)
                    for key in ("export_id", "file_name", "file_hash", "download_url", "review_report_id", "review_status")
                },
            }
        )
    return sorted(result, key=lambda resource: str(resource["resource_type"]))


def _task_evidence(base_url: str, task_id: str, *, expect_full_package: bool) -> dict[str, Any]:
    task = _poll_task(base_url, task_id, 420)
    if task.get("status") != "completed":
        raise AssertionError(f"task {task_id} ended as {task.get('status')}: {task.get('failure_reason')}")
    if task.get("thread_id") != task_id:
        raise AssertionError("task_id and thread_id differ")
    runs = _live_runs(base_url, task_id)
    roles = _review_roles(runs)
    if not {"primary_review_model", "secondary_review_model"}.issubset(roles):
        raise AssertionError(f"task {task_id} lacks dual review roles: {roles}")
    trace = _api_json(base_url, "GET", f"/generation-tasks/{task_id}/internal-trace")
    trace_runs = trace.get("runs") or []
    if (
        trace.get("thread_id") != task_id
        or not trace_runs
        or any(
            run.get("contract_version") != "agent-contract-v10"
            or len(str(run.get("prompt_hash") or "")) != 64
            for run in trace_runs
        )
        or not trace.get("messages")
    ):
        raise AssertionError(f"task {task_id} lacks V10 trace provenance")
    profile_updates = [
        bool((run.get("output_summary") or {}).get("profile_update_required"))
        for run in runs
        if _run_step(run) == "analyze_profile"
        and "profile_update_required" in (run.get("output_summary") or {})
    ]
    return {
        "task_id": task_id,
        "thread_id": task_id,
        "task_status": task["status"],
        "trigger_type": task.get("trigger_type"),
        "decision": task.get("decision"),
        "revision_count": task.get("revision_count"),
        "profile_update_required": profile_updates,
        "review_model_roles": roles,
        "agent_runs": _run_summary(runs),
        "structured_handoff_count": len(trace.get("messages") or []),
        "resources": _resource_summary(base_url, task_id, expect_full_package=expect_full_package),
    }


def _create_initial_task(base_url: str, case: dict[str, Any]) -> dict[str, Any]:
    created = _api_json(
        base_url,
        "POST",
        "/generation-tasks",
        {
            "learner_id": case["learner_id"],
            "profile_id": case["profile_id"],
            "domain_code": "smart_manufacturing",
            "trigger_type": "initial_generation",
            "execution_mode": "auto",
            "learning_goal": case["learning_goal"],
            "resource_types": case["resource_types"],
        },
    )
    return _task_evidence(base_url, str(created["task_id"]), expect_full_package=True)


def _resource_id(evidence: dict[str, Any], resource_type: str = "lecture") -> str:
    resource = next(
        (item for item in evidence["resources"] if item["resource_type"] == resource_type),
        None,
    )
    if resource is None:
        raise AssertionError(f"baseline has no {resource_type}")
    return str(resource["resource_id"])


def _run_incorrect_feedback(base_url: str, case: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    response = _api_json(
        base_url,
        "POST",
        f"/resources/{_resource_id(baseline)}/feedback",
        {
            "learner_id": case["learner_id"],
            "feedback_type": "incorrect",
            "selected_text": "提交测试：请重新检索来源并复核该资源中的事实表述。",
        },
    )
    if response.get("recommended_action") != "review" or not response.get("task_id"):
        raise AssertionError("incorrect feedback did not create a review task")
    evidence = _task_evidence(base_url, str(response["task_id"]), expect_full_package=False)
    if any(evidence["profile_update_required"]) or response.get("profile_update_required"):
        raise AssertionError("incorrect feedback must not update the learner profile")
    return {
        "feedback_id": response.get("feedback_id"),
        "recommended_action": response["recommended_action"],
        "profile_update_required": False,
        "task": evidence,
    }


def _run_challenge(base_url: str, case: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    session = _api_json(
        base_url,
        "POST",
        "/tutoring/sessions",
        {"learner_id": case["learner_id"], "resource_id": _resource_id(baseline)},
    )
    response = _api_json(
        base_url,
        "POST",
        f"/tutoring/sessions/{session['session_id']}/messages",
        {
            "content": "这部分太简单了，我已经掌握，请生成更难的迁移挑战。",
            "evidence": [
                {
                    "evidence_id": f"{case['case_id']}-confirmed-mastery",
                    "evidence_type": "validated_behavior",
                    "summary": "提交测试使用的已确认迁移任务完成行为。",
                    "knowledge_id": case["weak_knowledge_ids"][0],
                    "confidence": 0.9,
                    "confirmed": True,
                }
            ],
        },
        timeout=180,
    )
    if response.get("recommended_action") != "challenge":
        raise AssertionError(f"challenge request was not accepted: {response.get('recommended_action')}")
    task_id = response.get("task_id")
    if not task_id and response.get("feedback_id"):
        confirmed = _api_json(
            base_url,
            "POST",
            f"/generation-tasks/feedback/{response['feedback_id']}/confirm",
        )
        task_id = confirmed.get("task_id")
    if not task_id:
        raise AssertionError("challenge request did not expose a generation task")
    return {
        "session_id": session["session_id"],
        "recommended_action": "challenge",
        "task": _task_evidence(base_url, str(task_id), expect_full_package=False),
    }


def _case_markdown(case: dict[str, Any], result: dict[str, Any]) -> str:
    profile = result["input_profile"]
    baseline = result.get("baseline") or {}
    follow_up = result.get("follow_up") or {}
    lines = [
        f"# {case['case_id']}",
        "",
        "## 输入画像",
        "",
        f"- learner_id：`{case['learner_id']}`（合成测试标识）",
        f"- 画像类型：`{case['profile_type']}`",
        f"- 能力分数：理论 {profile['theory']}；实操 {profile['practice']}；问题解决 {profile['problem_solving']}；知识广度 {profile['breadth']}；学习速度 {profile['learning_speed']}",
        f"- 重点知识：{', '.join(f'`{item}`' for item in case['weak_knowledge_ids'])}",
        "",
        "## 协同与资源证据",
        "",
        f"- 初始任务：`{baseline.get('task_id')}`，状态 `{baseline.get('task_status')}`，thread_id 与 task_id 一致。",
        f"- 双审核角色：{', '.join(f'`{item}`' for item in baseline.get('review_model_roles', []))}。",
        f"- 结构化交接记录：{baseline.get('structured_handoff_count', 0)} 条；运行契约：`agent-contract-v10`。",
        "- 已导出并审核通过的资源：",
    ]
    for resource in baseline.get("resources", []):
        lines.append(
            f"  - `{resource['resource_type']}` / `{resource['resource_id']}` / 难度 {resource['difficulty']} / 导出 `{resource.get('submission_export_file') or resource['export']['file_name']}` / SHA-256 `{resource['export']['file_hash']}`"
        )
    if follow_up:
        task = follow_up.get("task") or {}
        lines.extend([
            "",
            "## 反馈后决策",
            "",
            f"- 推荐动作：`{follow_up.get('recommended_action')}`。",
            f"- 后续任务：`{task.get('task_id')}`，状态 `{task.get('task_status')}`。",
            f"- 画像更新：`{follow_up.get('profile_update_required', '由学情分析 Agent 按证据判定')}`。",
        ])
    lines.extend([
        "",
        "## 隐私说明",
        "",
        "本案例仅保存合成标识、画像分数、任务和审核摘要、来源知识标识及导出文件哈希；不保存完整资源正文、完整作答文本或原始 Agent payload。",
        "",
    ])
    return "\n".join(lines)


def _write_deliverables(report: dict[str, Any]) -> None:
    cases_dir = DELIVERABLE_DIR / "脱敏学习者案例"
    exports_dir = DELIVERABLE_DIR / "资源导出"
    cases_dir.mkdir(parents=True, exist_ok=True)
    exports_dir.mkdir(parents=True, exist_ok=True)
    for item in report["cases"]:
        for resource in (item.get("baseline") or {}).get("resources") or []:
            source_name = str((resource.get("export") or {}).get("file_name") or "")
            source = ROOT / "storage" / "exports" / Path(source_name).name
            if not source.is_file():
                raise AssertionError(f"export file is missing: {source_name}")
            target_name = f"{item['case']['case_id']}_{resource['resource_type']}.md"
            shutil.copy2(source, exports_dir / target_name)
            resource["submission_export_file"] = f"资源导出/{target_name}"
        filename = f"{item['case']['case_id']}.md"
        (cases_dir / filename).write_text(_case_markdown(item["case"], item), encoding="utf-8")
    status_lines = ["# 智能制造测试数据与案例包", "", f"状态：{report['status']}", ""]
    status_lines.extend(
        f"- `{item['case']['case_id']}`：{item['status']}（初始任务 `{(item.get('baseline') or {}).get('task_id', '')}`）"
        for item in report["cases"]
    )
    status_lines.extend([
        "",
        "本目录对应赛题的测试数据要求：一个垂直领域知识库切片与三组差异化学习者完整输入输出示例。它不包含智能制造领域的 50 例离线评测，也不以三例运行结果声明质量指标。",
        "",
        "复现：先运行 `scripts/submission-fixture.ps1 bootstrap -FixtureDir data/submission_fixtures/smart_manufacturing_v1 -ComposeProject cognivia_sm_test -ComposeFile docker-compose.submission.yml`，再运行 `python test_script/smart_manufacturing_demo_acceptance.py --base-url http://localhost:18000/api/v1`。",
        "",
    ])
    (DELIVERABLE_DIR / "README.md").write_text("\n".join(status_lines), encoding="utf-8")
    (DELIVERABLE_DIR / "运行报告.md").write_text("\n".join(status_lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run three live smart-manufacturing submission cases.")
    parser.add_argument("--base-url", default="http://localhost:18000/api/v1")
    parser.add_argument("--timeout-seconds", type=int, default=420)
    parser.add_argument("--username", default=os.getenv("EVALUATION_USERNAME", "admin"))
    parser.add_argument("--password", default=os.getenv("EVALUATION_PASSWORD") or os.getenv("INITIAL_ADMIN_PASSWORD"))
    args = parser.parse_args()
    if not args.password:
        raise SystemExit("set EVALUATION_PASSWORD/INITIAL_ADMIN_PASSWORD or pass --password")

    cases = _load_cases()
    _authenticate(args.base_url, args.username, args.password)
    health = _api_json(args.base_url, "GET", "/health/dependencies?domain_code=smart_manufacturing")
    runtime = health.get("domain_runtime") or {}
    if not runtime.get("generation_ready") or not (health.get("rag") or {}).get("ready"):
        raise SystemExit(f"smart_manufacturing runtime is not ready: {runtime.get('reasons')}")
    if health.get("evaluation_overrides_enabled"):
        raise SystemExit("live submission cases require ENABLE_EVALUATION_OVERRIDES=false")

    results: list[dict[str, Any]] = []
    for case in cases:
        profile_scores = next(
            item for item in json.loads((FIXTURE_DIR / "learner_profiles.json").read_text(encoding="utf-8"))
            if item["learner_id"] == case["learner_id"]
        )["ability_profile"]
        result: dict[str, Any] = {"case": case, "input_profile": profile_scores}
        try:
            baseline = _create_initial_task(args.base_url, case)
            result["baseline"] = baseline
            follow_up_type = (case.get("follow_up") or {}).get("type")
            if follow_up_type == "incorrect_feedback":
                result["follow_up"] = _run_incorrect_feedback(args.base_url, case, baseline)
            elif follow_up_type == "challenge_request":
                result["follow_up"] = _run_challenge(args.base_url, case, baseline)
            result["status"] = "passed"
        except Exception as exc:
            result["status"] = "failed"
            result["error"] = _safe_error(exc)
        results.append(result)

    report = {
        "schema_version": "smart-manufacturing-live-demo-report-v1",
        "status": "passed" if all(item["status"] == "passed" for item in results) else "failed",
        "provider_mode": "live",
        "domain_code": "smart_manufacturing",
        "fixture_version": "smart_manufacturing_submission_fixture_v1",
        "evaluated_at": datetime.now(UTC).isoformat(),
        "model_configuration": {
            key: (health.get(key) or {}).get("model_name")
            for key in ("generation_model", "primary_review_model", "secondary_review_model")
        },
        "cases": results,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_deliverables(report)
    # Persist the relative export paths added during submission-artifact staging.
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
