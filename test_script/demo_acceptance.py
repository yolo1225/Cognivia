from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from run_live import _api_json, _authenticate, _poll_task


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "demo"
STAGE0_BRANCH_IDS = ("initial_generation", "no_change", "incorrect_review")
TUTORING_TIMEOUT_SECONDS = 180


def _report_error(exc: Exception) -> str:
    """Keep machine evidence useful without retaining reply or resource bodies."""
    message = " ".join(str(exc).split())
    if "{" in message:
        message = message.split("{", 1)[0].rstrip(" :")
    return message[:500] or type(exc).__name__


def _create_task(
    base_url: str, *, learner_id: str, goal: str, resource_types: list[str]
) -> dict[str, Any]:
    created = _api_json(
        base_url,
        "POST",
        "/generation-tasks",
        {
            "learner_id": learner_id,
            "domain_code": "ai_app_dev",
            "trigger_type": "initial_generation",
            "execution_mode": "auto",
            "learning_goal": goal,
            "resource_types": resource_types,
        },
    )
    return _poll_task(base_url, str(created["task_id"]), 360)


def _live_runs(base_url: str, task_id: str) -> list[dict[str, Any]]:
    runs = _api_json(base_url, "GET", f"/generation-tasks/{task_id}/agent-runs")
    model_runs = [run for run in runs if run.get("model_name")]
    if not model_runs or any(
        (run.get("output_summary") or {}).get("provider_mode") != "live" for run in model_runs
    ):
        raise AssertionError(f"task {task_id} does not contain exclusively live model calls")
    return runs


def _current_resource(
    base_url: str, learner_id: str, resource_type: str = "lecture"
) -> dict[str, Any]:
    resources = _api_json(base_url, "GET", f"/resources?learner_id={learner_id}")
    resource = next(
        (
            item
            for item in resources
            if item.get("resource_type") == resource_type
            and item.get("review_status") == "passed"
            and (item.get("package_quality") or {}).get("quality_rule_version")
            == "quality-v6-20260818"
        ),
        None,
    )
    if resource is None:
        raise AssertionError(f"no current passed V6 {resource_type} resource found")
    return resource


def _profile_updated(runs: list[dict[str, Any]]) -> bool:
    return any(
        (run.get("input_summary") or {}).get("step") == "analyze_profile"
        and bool((run.get("output_summary") or {}).get("profile_update_required"))
        for run in runs
    )


def _step_runs(runs: list[dict[str, Any]], step: str) -> list[dict[str, Any]]:
    return [
        run
        for run in runs
        if (run.get("input_summary") or {}).get("step") == step
    ]


def _stage0_task_evidence(
    base_url: str,
    task: dict[str, Any],
    runs: list[dict[str, Any]],
    *,
    expect_three_resources: bool,
) -> dict[str, Any]:
    task_id = str(task["task_id"])
    if task.get("thread_id") != task_id:
        raise AssertionError("task_id and thread_id must match")
    if task.get("status") != "completed":
        raise AssertionError(f"task {task_id} did not complete: {task.get('status')}")

    resources = _api_json(base_url, "GET", f"/resources?task_id={task_id}")
    expected_types = {"lecture", "practice_guide", "graded_quiz"}
    resource_types = {str(item.get("resource_type")) for item in resources}
    if expect_three_resources and resource_types != expected_types:
        raise AssertionError(f"task {task_id} did not publish all resource types: {resource_types}")
    if not resources:
        raise AssertionError(f"task {task_id} has no published resources")
    for resource in resources:
        if resource.get("review_status") != "passed":
            raise AssertionError(f"resource {resource.get('resource_id')} is not passed")
        if not resource.get("sources") or not resource.get("source_details"):
            raise AssertionError(f"resource {resource.get('resource_id')} has no knowledge sources")
        if not resource.get("difficulty") or not resource.get("quality_metrics"):
            raise AssertionError(f"resource {resource.get('resource_id')} lacks quality metadata")

    review_runs = _step_runs(runs, "review_resource")
    model_roles = {
        str(call.get("role"))
        for run in review_runs
        for call in ((run.get("output_summary") or {}).get("model_calls") or [])
        if call.get("role")
    }
    if not {"primary_review_model", "secondary_review_model"}.issubset(model_roles):
        raise AssertionError("review runs do not contain independent primary and secondary calls")
    profile_decisions = [
        bool((run.get("output_summary") or {}).get("profile_update_required"))
        for run in _step_runs(runs, "analyze_profile")
        if "profile_update_required" in (run.get("output_summary") or {})
    ]
    # ReviewReport stores the final review state for each published resource.
    # Earlier review runs remain in AgentRun as revision history, so comparing
    # the report count with every historical run double-counts arbitration.
    final_review_runs = review_runs[-1:]
    arbitration_count = 0
    for run in final_review_runs:
        arbitration = (run.get("output_summary") or {}).get("arbitration") or []
        if isinstance(arbitration, dict):
            arbitration = [arbitration]
        arbitration_count += sum(
            1 for item in arbitration if isinstance(item, dict) and item.get("required")
        )
    trace = _api_json(base_url, "GET", f"/generation-tasks/{task_id}/internal-trace")
    if trace.get("thread_id") != task_id:
        raise AssertionError("internal trace thread_id does not match task_id")
    trace_runs = trace.get("runs") or []
    if not trace_runs or any(
            run.get("contract_version") != "agent-contract-v9"
        or len(str(run.get("prompt_hash") or "")) != 64
        for run in trace_runs
    ):
        raise AssertionError("internal trace lacks V9 contract or Prompt provenance")
    if not trace.get("messages"):
        raise AssertionError("internal trace has no structured handoff records")
    trace_arbitrations = sum(
        1
        for report in (trace.get("reviews") or [])
        if (report.get("arbitration") or {}).get("required") is True
    )
    if trace_arbitrations != arbitration_count:
        raise AssertionError("review run and persisted arbitration evidence disagree")
    return {
        "task_id": task_id,
        "thread_id": task_id,
        "resource_count": len(resources),
        "resource_types": sorted(resource_types),
        "review_model_roles": sorted(model_roles),
        "review_call_count": sum(
            len((run.get("output_summary") or {}).get("model_calls") or [])
            for run in review_runs
        ),
        "profile_update_required": profile_decisions,
        "arbitration_count": arbitration_count,
        "structured_handoff_count": len(trace.get("messages") or []),
        "revision_count": int(task.get("revision_count") or 0),
        "duration_ms": sum(int(run.get("duration_ms") or 0) for run in runs),
    }


def _assessment_option(question_id: str, *, correct: bool) -> int:
    """Resolve an answer server-side without exposing the answer key in reports."""
    backend_root = ROOT / "backend"
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))
    from sqlalchemy import select

    from app.core.db import SessionLocal
    from app.models import DiagnosticQuestion

    with SessionLocal() as db:
        question = db.scalar(
            select(DiagnosticQuestion).where(DiagnosticQuestion.public_id == question_id)
        )
        if question is None:
            raise AssertionError("tutoring assessment question is missing")
        correct_option = int((question.answer_key_json or {}).get("correct_option", -1))
        option_count = len(question.options_json or [])
        if correct_option < 0 or correct_option >= option_count:
            raise AssertionError("tutoring assessment answer key is invalid")
        if correct:
            return correct_option
        return next(index for index in range(option_count) if index != correct_option)


def _run_revision_fixture() -> dict[str, Any]:
    """Run deterministic arbitration and two-revision graph fixtures."""
    tests = [
        "backend/tests/integration/test_v3_review_arbitration_retrieval.py::"
        "test_v3_review_arbitration_retrieves_real_candidate_evidence",
        "backend/tests/integration/test_v3_graph_runtime.py::"
        "test_v3_graph_stops_after_two_revisions_using_prior_finalize_output",
    ]
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *tests],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError("deterministic arbitration/revision fixture failed")
    return {
        "fixture": "deterministic_backend_graph",
        "arbitration_retrieval_verified": True,
        "revision_count": 2,
        "publication_blocked": True,
    }


def _acceptance_learner(base_url: str, requested: str | None) -> str:
    learners = _api_json(base_url, "GET", "/learners")
    ready = [
        item
        for item in learners
        if item.get("profile_status") == "ready"
        and item.get("target_domain") == "ai_app_dev"
    ]
    if requested:
        selected = next((item for item in ready if item.get("learner_id") == requested), None)
        if selected is None:
            raise ValueError("requested acceptance learner lacks a normal ready profile")
        return requested
    if not ready:
        raise ValueError("no normal learner with a ready ai_app_dev profile is available")
    return str(sorted(ready, key=lambda item: str(item.get("learner_id")))[0]["learner_id"])


def _completed_live_baseline(base_url: str, learner_id: str) -> dict[str, Any]:
    tasks = _api_json(
        base_url,
        "GET",
        f"/generation-tasks?learner_id={learner_id}&status=completed&limit=100",
    )
    expected = {"lecture", "practice_guide", "graded_quiz"}
    for task in tasks:
        resource_types = {
            str(item.get("resource_type")) for item in (task.get("resources") or [])
        }
        if task.get("trigger_type") != "initial_generation" or resource_types != expected:
            continue
        _live_runs(base_url, str(task["task_id"]))
        return task
    raise AssertionError("no completed three-resource live baseline is available")


def _load_snapshot(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    for branch in ("revision_exhausted",):
        item = payload.get(branch)
        if item is None:
            continue
        required = {"task_id", "recorded_at", "model_names", "provider_mode"}
        if not required.issubset(item) or item["provider_mode"] != "live":
            raise ValueError(f"snapshot branch {branch} is missing live-run evidence")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the automated Docker demo acceptance branches.")
    parser.add_argument(
        "--suite",
        choices=("full", "stage0"),
        default="full",
        help="stage0 runs only the frozen initial-generation and feedback branches",
    )
    parser.add_argument("--base-url", default="http://localhost:8000/api/v1")
    parser.add_argument("--snapshot", type=Path, help="optional live snapshot for revision exhaustion")
    parser.add_argument("--username", default=os.getenv("EVALUATION_USERNAME", "admin"))
    parser.add_argument("--password", default=os.getenv("EVALUATION_PASSWORD"))
    parser.add_argument("--learner-id", default=os.getenv("DEMO_ACCEPTANCE_LEARNER_ID"))
    parser.add_argument("--baseline-task-id", default=os.getenv("DEMO_ACCEPTANCE_TASK_ID"))
    args = parser.parse_args()

    if not args.password:
        raise SystemExit("set EVALUATION_PASSWORD or pass --password")
    _authenticate(args.base_url, args.username, args.password)
    health = _api_json(args.base_url, "GET", "/health/dependencies")
    if not health.get("ready_for_live_demo") or not (health.get("rag") or {}).get("ready"):
        raise SystemExit("real model channels or candidate RAG are not ready")
    if args.suite == "stage0" and health.get("evaluation_overrides_enabled"):
        raise SystemExit("stage0 requires ENABLE_EVALUATION_OVERRIDES=false")
    snapshots = _load_snapshot(args.snapshot)
    learner_id = _acceptance_learner(args.base_url, args.learner_id)
    context: dict[str, Any] = {}
    branches: list[dict[str, Any]] = []

    def run_branch(branch_id: str, title: str, action: Callable[[], dict[str, Any]]) -> None:
        try:
            evidence = action()
            branches.append({"branch_id": branch_id, "title": title, "status": "passed", **evidence})
        except Exception as exc:
            snapshot = snapshots.get(branch_id)
            if snapshot:
                branches.append(
                    {
                        "branch_id": branch_id,
                        "title": title,
                        "status": "passed_from_live_snapshot",
                        "live_snapshot": snapshot,
                        "live_attempt_error": _report_error(exc),
                    }
                )
            else:
                branches.append(
                    {
                        "branch_id": branch_id,
                        "title": title,
                        "status": "failed",
                        "error": _report_error(exc),
                    }
                )

    def initial_generation() -> dict[str, Any]:
        live_attempt = (
            _api_json(
                args.base_url,
                "GET",
                f"/generation-tasks/{args.baseline_task_id}",
            )
            if args.baseline_task_id
            else _create_task(
                args.base_url,
                learner_id=learner_id,
                goal="生成可追溯的个性化讲义、实操指南和分阶测验",
                resource_types=["lecture", "practice_guide", "graded_quiz"],
            )
        )
        if live_attempt.get("learner_id") != learner_id:
            raise AssertionError("baseline task learner does not match acceptance learner")
        task = live_attempt
        evidence_source = (
            "specified_completed_live_baseline"
            if args.baseline_task_id
            else "current_live_attempt"
        )
        if task["status"] != "completed" or len(task.get("resources", [])) != 3:
            task = _completed_live_baseline(args.base_url, learner_id)
            evidence_source = "prior_completed_live_baseline"
        task_resources = _api_json(
            args.base_url, "GET", f"/resources?task_id={task['task_id']}"
        )
        resource = next(
            (item for item in task_resources if item.get("resource_type") == "lecture"),
            None,
        )
        if resource is None:
            raise AssertionError("completed baseline has no lecture resource")
        # The completed baseline is immutable historical evidence. A later
        # feedback run may have replaced its resource version, so tutoring
        # must attach to the learner's current passed V6 package member.
        context["resource_id"] = _current_resource(
            args.base_url, learner_id, "lecture"
        )["resource_id"]
        runs = _live_runs(args.base_url, task["task_id"])
        evidence = _stage0_task_evidence(
            args.base_url, task, runs, expect_three_resources=True
        )
        return {
            **evidence,
            "evidence_source": evidence_source,
            "live_attempt_task_id": live_attempt["task_id"],
            "live_attempt_status": live_attempt["status"],
        }

    def no_change_explanation() -> dict[str, Any]:
        session = _api_json(
            args.base_url,
            "POST",
            "/tutoring/sessions",
            {"learner_id": learner_id, "resource_id": context["resource_id"]},
        )
        response = _api_json(
            args.base_url,
            "POST",
            f"/tutoring/sessions/{session['session_id']}/messages",
            {"content": "这部分太难了，我第一次没有看懂。"},
            timeout=TUTORING_TIMEOUT_SECONDS,
        )
        if response.get("recommended_action") != "no_change" or response.get("task_id"):
            raise AssertionError(f"first subjective feedback must not change profile: {response}")
        context["session_id"] = session["session_id"]
        assessment = (response.get("reply") or {}).get("assessment")
        if not assessment:
            raise AssertionError("first difficulty feedback did not create a formal assessment")
        context["first_assessment"] = assessment
        if response.get("profile_update_required"):
            raise AssertionError(f"first subjective feedback updated profile: {response}")
        return {
            "session_id": session["session_id"],
            "decision": "no_change",
            "profile_update_required": False,
            "feedback_task_count": 0,
            "path_completed_node_count": 0,
        }

    def evidence_profile_update() -> dict[str, Any]:
        first = context["first_assessment"]
        first_answer = _api_json(
            args.base_url,
            "POST",
            f"/tutoring/sessions/{context['session_id']}/assessments/"
            f"{first['assessment_id']}/answers",
            {"answer": _assessment_option(first["question_id"], correct=False)},
            timeout=TUTORING_TIMEOUT_SECONDS,
        )
        if first_answer.get("is_correct") or first_answer.get("task_id"):
            raise AssertionError("first failed validation must not create a profile task")

        response = _api_json(
            args.base_url,
            "POST",
            f"/tutoring/sessions/{context['session_id']}/messages",
            {"content": "我按补救解释重做后仍然答错，需要更基础的解释。"},
            timeout=TUTORING_TIMEOUT_SECONDS,
        )
        second = (response.get("reply") or {}).get("assessment")
        if not second:
            raise AssertionError("remedial turn did not create a second formal assessment")
        second_answer = _api_json(
            args.base_url,
            "POST",
            f"/tutoring/sessions/{context['session_id']}/assessments/"
            f"{second['assessment_id']}/answers",
            {"answer": _assessment_option(second["question_id"], correct=False)},
            timeout=360,
        )
        task_id = second_answer.get("task_id")
        if not task_id:
            raise AssertionError("second failed formal validation did not create a profile task")
        _poll_task(args.base_url, task_id, 360)
        runs = _live_runs(args.base_url, task_id)
        if not _profile_updated(runs):
            raise AssertionError("profile update was not recorded by analyze_profile")
        return {
            "task_id": task_id,
            "profile_update": True,
            "answer_record_count": 2,
            "evidence_source": "server_scored_tutoring_assessment",
        }

    def incorrect_review() -> dict[str, Any]:
        resource = _current_resource(args.base_url, learner_id)
        response = _api_json(
            args.base_url,
            "POST",
            f"/resources/{resource['resource_id']}/feedback",
            {
                "learner_id": learner_id,
                "feedback_type": "incorrect",
                "selected_text": "这一处事实与来源不一致，请复核。",
            },
        )
        task_id = response.get("task_id")
        if not task_id:
            raise AssertionError("incorrect feedback did not create a review task")
        task = _poll_task(args.base_url, task_id, 360)
        runs = _live_runs(args.base_url, task_id)
        evidence = _stage0_task_evidence(
            args.base_url, task, runs, expect_three_resources=False
        )
        if any(evidence["profile_update_required"]):
            raise AssertionError("incorrect feedback must not update the learner profile")
        return {
            **evidence,
            "recommended_action": response["recommended_action"],
            "feedback_task_count": 1,
            "path_completed_node_count": 0,
        }

    def challenge_task() -> dict[str, Any]:
        resource = _current_resource(args.base_url, learner_id)
        session = _api_json(
            args.base_url,
            "POST",
            "/tutoring/sessions",
            {"learner_id": learner_id, "resource_id": resource["resource_id"]},
        )
        response = _api_json(
            args.base_url,
            "POST",
            f"/tutoring/sessions/{session['session_id']}/messages",
            {
                "content": "这部分太简单了，我已经掌握，请给我更难的迁移挑战。",
                "evidence": [
                    {
                        "evidence_id": f"acceptance_mastery_{session['session_id']}",
                        "type": "scored_quiz",
                        "knowledge_id": "rag_pipeline_overview",
                        "confidence": 0.95,
                        "confirmed": True,
                    }
                ],
            },
            timeout=TUTORING_TIMEOUT_SECONDS,
        )
        task_id = response.get("task_id")
        if response.get("recommended_action") != "challenge" or not task_id:
            raise AssertionError(f"challenge message did not create task: {response}")
        _poll_task(args.base_url, task_id, 360)
        _live_runs(args.base_url, task_id)
        return {"task_id": task_id, "recommended_action": "challenge"}

    def revision_exhausted() -> dict[str, Any]:
        return _run_revision_fixture()

    run_branch("initial_generation", "首次生成三类资源", initial_generation)
    run_branch("no_change", "证据不足，仅解释且画像不变", no_change_explanation)
    if args.suite == "full":
        run_branch("profile_update", "多轮证据创建画像新版本", evidence_profile_update)
    run_branch("incorrect_review", "错误反馈触发资源复核", incorrect_review)
    if args.suite == "full":
        run_branch("challenge", "掌握后生成挑战任务", challenge_task)
        run_branch("revision_exhausted", "两轮自动修订后失败", revision_exhausted)

    report = {
        "status": "passed" if all(item["status"].startswith("passed") for item in branches) else "failed",
        "suite": args.suite,
        "provider_mode": "live",
        "learner_id": learner_id,
        "model_configuration": {
            "generation_model": health["generation_model"]["model_name"],
            "primary_review_model": health["primary_review_model"]["model_name"],
            "secondary_review_model": health["secondary_review_model"]["model_name"],
        },
        "evaluated_at": datetime.now(UTC).isoformat(),
        "branches": branches,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = ["# Docker 自动闭环演示验收", "", f"状态：{report['status']}", ""]
    lines.extend(
        f"- {item['title']}：{item['status']}（{item.get('task_id') or item.get('error', '')}）"
        for item in branches
    )
    (REPORT_DIR / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    # The acceptance evidence is UTF-8 JSON.  Reconfigure Windows console output
    # so a provider reply can never make a completed run fail during reporting.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
