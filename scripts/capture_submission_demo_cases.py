"""Capture three real, privacy-safe submission cases through the public business APIs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import time
from datetime import UTC, datetime
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "data" / "submission_fixtures" / "ai_app_dev_v1" / "diagnostic_questions.json"
RESOURCE_TYPES = ("lecture", "practice_guide", "graded_quiz")
OBJECTIVE_QUESTION_TYPES = {"single_choice", "multiple_choice"}
TERMINAL_TASK_STATUSES = {"completed", "failed", "revision_required", "no_change", "rejected"}

CASE_SPECS = (
    {
        "case_name": "初学者_完整输入输出",
        "case_id": "SUBMISSION-BEGINNER-INITIAL",
        "answer_strategy": "all_incorrect",
        "education_level": "中职/高中",
        "major": "非计算机专业",
        "experience_years": 0,
        "learning_style": "practice",
        "direction_tags": ["application_engineering"],
        "goal": "掌握 AI 应用开发基础流程，并完成一次具备超时和异常处理的 API 调用练习。",
        "follow_up": "none",
    },
    {
        "case_name": "进阶学习者_完整输入输出",
        "case_id": "SUBMISSION-INTERMEDIATE-FEEDBACK",
        "answer_strategy": "alternating",
        "education_level": "本科",
        "major": "软件工程",
        "experience_years": 1,
        "learning_style": "mixed",
        "direction_tags": ["prompt_engineering", "rag_knowledge_base"],
        "goal": "掌握 Prompt 上下文设计与 RAG 检索调试，并形成可复核的实操步骤。",
        "follow_up": "incorrect_feedback",
    },
    {
        "case_name": "高阶学习者_完整输入输出",
        "case_id": "SUBMISSION-ADVANCED-CHALLENGE",
        "answer_strategy": "all_correct",
        "education_level": "硕士及以上",
        "major": "人工智能",
        "experience_years": 3,
        "learning_style": "theory",
        "direction_tags": ["agent_orchestration", "llm_application"],
        "goal": "完成多智能体审核仲裁的挑战任务，解释证据冲突后的检索、复核和发布决策。",
        "follow_up": "challenge",
    },
)


class ApiFailure(RuntimeError):
    pass


COOKIE_JAR = CookieJar()
HTTP_OPENER = build_opener(HTTPCookieProcessor(COOKIE_JAR))


def csrf_token() -> str | None:
    return next((cookie.value for cookie in COOKIE_JAR if cookie.name == "csrf_token"), None)


def api_json_with_session(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None,
    *,
    opener: Any,
    cookies: CookieJar,
    timeout: int = 60,
) -> Any:
    headers = {"Content-Type": "application/json"}
    if token := next((cookie.value for cookie in cookies if cookie.name == "csrf_token"), None):
        headers["X-CSRF-Token"] = token
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None,
        method=method,
        headers=headers,
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            envelope = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ApiFailure(f"{method} {path} returned {exc.code}: {detail[:500]}") from exc
    except (URLError, TimeoutError) as exc:
        raise ApiFailure(f"{method} {path} failed: {exc}") from exc
    if envelope.get("error"):
        raise ApiFailure(f"{method} {path} returned API error: {envelope['error']}")
    return envelope.get("data")


def api_json(base_url: str, method: str, path: str, payload: dict[str, Any] | None = None, *, timeout: int = 60) -> Any:
    return api_json_with_session(
        base_url, method, path, payload, opener=HTTP_OPENER, cookies=COOKIE_JAR, timeout=timeout
    )


def admin_session(base_url: str, username: str, password: str) -> tuple[Any, CookieJar]:
    cookies = CookieJar()
    opener = build_opener(HTTPCookieProcessor(cookies))
    api_json_with_session(
        base_url,
        "POST",
        "/auth/login",
        {"username": username, "password": password},
        opener=opener,
        cookies=cookies,
    )
    if not any(cookie.name == "csrf_token" for cookie in cookies):
        raise ApiFailure("administrator login did not establish a CSRF token")
    return opener, cookies


def download(base_url: str, path: str, destination: Path) -> None:
    parsed_base = urlsplit(base_url)
    origin = f"{parsed_base.scheme}://{parsed_base.netloc}"
    download_url = path if path.startswith(("http://", "https://")) else f"{origin}{path}"
    request = Request(quote(download_url, safe=":/?&=.%_-"), headers={"X-CSRF-Token": csrf_token() or ""})
    try:
        with HTTP_OPENER.open(request, timeout=120) as response:
            destination.write_bytes(response.read())
    except (HTTPError, URLError, TimeoutError) as exc:
        raise ApiFailure(f"download {path} failed: {exc}") from exc


def reset_session() -> None:
    COOKIE_JAR.clear()


def register_learner(base_url: str, username: str, display_name: str) -> str:
    reset_session()
    password = f"Submission_{secrets.token_urlsafe(18)}"
    account = api_json(base_url, "POST", "/auth/register", {
        "username": username,
        "password": password,
        "display_name": display_name,
    })
    if not csrf_token():
        raise ApiFailure("registration did not establish a CSRF token")
    return str(account["learner_id"])


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture_questions() -> dict[str, dict[str, Any]]:
    rows = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return {str(row["question_id"]): row for row in rows}


def diagnostic_answers(session: dict[str, Any], strategy: str, questions: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    submitted: list[dict[str, Any]] = []
    redacted: list[dict[str, Any]] = []
    for index, shown in enumerate(session["questions"]):
        question_id = str(shown["question_id"])
        source = questions.get(question_id)
        if source is None:
            raise ApiFailure(f"diagnostic question is absent from fixture: {question_id}")
        intended_correct = strategy == "all_correct" or (strategy == "alternating" and index % 2 == 0)
        answer_key = source["answer_key"]
        if source["question_type"] == "single_choice":
            correct = int(answer_key["correct_option"])
            answer: int | str = correct if intended_correct else (correct + 1) % 4
            redacted.append({"question_id": question_id, "question_type": "single_choice", "selected_option": answer, "intended_correct": intended_correct})
        else:
            answer = "；".join(answer_key.get("rubric") or []) if intended_correct else "暂不能说明具体做法。"
            redacted.append({"question_id": question_id, "question_type": "short_answer", "response_sha256": hashlib.sha256(answer.encode("utf-8")).hexdigest(), "response_length": len(answer), "intended_correct": intended_correct})
        submitted.append({"question_id": question_id, "answer": answer})
    return submitted, redacted


def poll_diagnostic(base_url: str, session_id: str, learner_id: str, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status = api_json(base_url, "GET", f"/diagnostics/sessions/{session_id}?learner_id={learner_id}")
        if status.get("status") in {"scored", "failed"}:
            if status["status"] != "scored" or not status.get("result"):
                raise ApiFailure(f"diagnostic failed: {status.get('error_code')}")
            return status
        time.sleep(1)
    raise ApiFailure(f"diagnostic timed out: {session_id}")


def poll_task(base_url: str, task_id: str, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        task = api_json(base_url, "GET", f"/generation-tasks/{task_id}")
        if task.get("status") in TERMINAL_TASK_STATUSES:
            if task["status"] != "completed":
                raise ApiFailure(f"task {task_id} ended as {task['status']}: {task.get('failure_reason')}")
            return task
        time.sleep(1)
    raise ApiFailure(f"generation task timed out: {task_id}")


def concise_diagnostic(status: dict[str, Any]) -> dict[str, Any]:
    result = status["result"]
    return {
        "session_id": result["session_id"],
        "learner_id": result["learner_id"],
        "status": status["status"],
        "score": result["score"],
        "correct_count": result["correct_count"],
        "question_count": result["question_count"],
        "profile_id": result["profile_id"],
        "profile_type": result["profile_type"],
        "ability_profile": result["ability_profile"],
        "weak_knowledge": [
            {key: row.get(key) for key in ("knowledge_id", "name", "category", "weakness_level")}
            for row in result.get("weak_knowledge", [])
        ],
        "answer_results": [
            {key: row.get(key) for key in ("question_id", "question_type", "score", "is_correct", "scoring_method", "confidence", "scoring_uncertain")}
            for row in result.get("answer_results", [])
        ],
    }


def task_summary(task: dict[str, Any]) -> dict[str, Any]:
    return {
        key: task.get(key)
        for key in ("task_id", "thread_id", "status", "decision", "trigger_type", "event_type", "source_task_id", "learner_id", "profile_id", "path_id", "path_node_id", "revision_count", "package_quality", "package_coverage", "source_feedback")
    } | {
        "resources": [
            {key: resource.get(key) for key in ("resource_id", "resource_type", "title", "difficulty", "review_status", "version", "is_current", "sources", "knowledge_coverage", "membership_type")}
            for resource in task.get("resources", [])
        ]
    }


def capture_trace(base_url: str, task_id: str, admin_opener: Any, admin_cookies: CookieJar) -> tuple[dict[str, Any], dict[str, Any]]:
    trace = api_json_with_session(
        base_url,
        "GET",
        f"/generation-tasks/{task_id}/internal-trace",
        None,
        opener=admin_opener,
        cookies=admin_cookies,
    )
    agent_trace = {
        "task_id": trace["task_id"],
        "thread_id": trace["thread_id"],
        "decision": trace["decision"],
        "revision_count": trace["revision_count"],
        "runs": trace.get("runs", []),
        "messages": trace.get("messages", []),
    }
    review = {
        "task_id": trace["task_id"],
        "reviews": trace.get("reviews", []),
    }
    return agent_trace, review


def export_resources(base_url: str, task: dict[str, Any], destination: Path) -> list[dict[str, Any]]:
    destination.mkdir(parents=True, exist_ok=True)
    by_type = {str(resource.get("resource_type")): resource for resource in task.get("resources", [])}
    if set(by_type) != set(RESOURCE_TYPES):
        raise ApiFailure(f"final package does not contain all resource types: {sorted(by_type)}")
    exported: list[dict[str, Any]] = []
    for resource_type in RESOURCE_TYPES:
        resource = by_type[resource_type]
        if resource.get("review_status") != "passed" or not resource.get("sources"):
            raise ApiFailure(f"resource is not approved or lacks sources: {resource_type}")
        payload = api_json(base_url, "POST", f"/resources/{resource['resource_id']}/export", {"format": "markdown", "audience": "learner"})
        file_name = f"{resource_type}.md"
        target = destination / file_name
        download(base_url, str(payload["download_url"]), target)
        exported.append({"resource_id": resource["resource_id"], "resource_type": resource_type, "file": file_name, "sha256": sha256(target)})
    return exported


def complete_current_graded_quiz(
    base_url: str,
    learner_id: str,
    task_id: str,
) -> dict[str, Any]:
    resources = api_json(base_url, "GET", f"/resources?task_id={task_id}")
    quiz = next((item for item in resources if item.get("resource_type") == "graded_quiz"), None)
    questions = ((quiz or {}).get("structured_content") or {}).get("questions") or []
    objective_questions = [
        item for item in questions
        if isinstance(item, dict) and str(item.get("question_type") or "") in OBJECTIVE_QUESTION_TYPES
    ]
    if quiz is None or not objective_questions:
        raise ApiFailure("current package does not expose a usable graded quiz")
    attempt = api_json(
        base_url,
        "POST",
        f"/resources/{quiz['resource_id']}/quiz-attempts",
        {"learner_id": learner_id},
    )
    submitted: list[dict[str, Any]] = []
    for question in objective_questions:
        question_id = str(question.get("question_id") or "")
        correct_answer = question.get("correct_answer")
        if not question_id or correct_answer is None:
            raise ApiFailure(f"graded quiz has no answerable objective question: {question}")
        if str(question.get("question_type")) == "single_choice":
            payload_answer: str | list[str] = str(correct_answer).strip()
        else:
            payload_answer = [
                item.strip()
                for item in str(correct_answer).replace("；", "、").split("、")
                if item.strip()
            ]
        result = api_json(
            base_url,
            "PUT",
            f"/resources/{quiz['resource_id']}/quiz-attempts/{attempt['attempt_id']}/answers/{question_id}",
            {"learner_id": learner_id, "answer": payload_answer},
        )
        if result.get("correct") is not True:
            raise ApiFailure(f"graded quiz answer was not accepted as correct: {question_id}")
        submitted.append({"question_id": question_id, "question_type": question["question_type"], "correct": True})
    completed = api_json(
        base_url,
        "POST",
        f"/resources/{quiz['resource_id']}/quiz-attempts/{attempt['attempt_id']}/complete",
        {"learner_id": learner_id},
    )
    return {
        "resource_id": quiz["resource_id"],
        "attempt_id": attempt["attempt_id"],
        "submitted_objective_questions": submitted,
        "completion": completed,
    }


def follow_up(
    base_url: str,
    spec: dict[str, Any],
    learner_id: str,
    initial_task: dict[str, Any],
    timeout_seconds: int,
    questions: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    follow_up_type = spec["follow_up"]
    if follow_up_type == "none":
        return initial_task, {"type": "none", "profile_update_decision": initial_task.get("decision")}
    resource_type = "practice_guide" if follow_up_type == "incorrect_feedback" else "graded_quiz"
    resource = next((item for item in initial_task["resources"] if item.get("resource_type") == resource_type), None)
    if resource is None:
        raise ApiFailure(f"initial package does not contain {resource_type}")
    if follow_up_type == "incorrect_feedback":
        response = api_json(base_url, "POST", f"/resources/{resource['resource_id']}/feedback", {
            "learner_id": learner_id,
            "feedback_type": "incorrect",
            "rating": 2,
            "selected_text": "请重新检索该实操步骤的来源依据，并核对其正确性。",
        })
        if response.get("recommended_action") != "review" or not response.get("task_id"):
            raise ApiFailure(f"incorrect feedback did not create a review task: {response}")
    else:
        session = api_json(base_url, "POST", "/tutoring/sessions", {"learner_id": learner_id, "resource_id": resource["resource_id"]})
        turns: list[dict[str, Any]] = []
        for turn in range(2):
            response = api_json(base_url, "POST", f"/tutoring/sessions/{session['session_id']}/messages", {
                "content": "当前内容已经掌握，请提供更高难度的多智能体审核仲裁挑战任务。",
                "evidence": [{
                    "evidence_id": f"{spec['case_id']}-validated-mastery-{turn + 1}",
                    "evidence_type": "validated_behavior",
                    "summary": "已确认完成基础学习任务并能够解释核心流程。",
                    "knowledge_id": str(resource.get("sources", [""])[0]),
                    "confidence": 0.95,
                    "confirmed": True,
                }],
            })
            if response.get("recommended_action") != "challenge":
                raise ApiFailure(f"advanced feedback did not recommend a challenge: {response}")
            turns.append(response)
        assessment = (
            (turns[-1].get("reply") or {}).get("assessment")
            or turns[-1].get("assessment")
            or {}
        )
        assessment_id = str(assessment.get("assessment_id") or "")
        question_id = str(assessment.get("question_id") or "")
        source_question = questions.get(question_id)
        if not assessment_id or source_question is None:
            raise ApiFailure(f"challenge did not produce a fixture-backed mastery assessment: {assessment}")
        quiz_result = complete_current_graded_quiz(base_url, learner_id, str(initial_task["task_id"]))
        correct_option = int(source_question["answer_key"]["correct_option"])
        assessment_result = api_json(
            base_url,
            "POST",
            f"/tutoring/sessions/{session['session_id']}/assessments/{assessment_id}/answers",
            {"answer": correct_option},
        )
        proposal_id = str(assessment_result.get("adjustment_proposal_id") or "")
        if not proposal_id:
            raise ApiFailure(f"challenge assessment did not produce an adjustment proposal: {assessment_result}")
        response = api_json(
            base_url,
            "POST",
            f"/learning-adjustments/{proposal_id}/resource-decision",
            {"decision": "generate"},
        )
        if not response.get("task_id"):
            raise ApiFailure(f"challenge resource decision did not create a task: {response}")
    final_task = poll_task(base_url, str(response["task_id"]), timeout_seconds)
    return final_task, {
        "type": follow_up_type,
        "source_resource_id": resource["resource_id"],
        "response": response,
        **(
            {"tutoring_session_id": session["session_id"], "tutoring_turns": turns, "assessment": assessment, "graded_quiz_result": quiz_result, "assessment_result": assessment_result, "proposal_id": proposal_id}
            if follow_up_type == "challenge"
            else {}
        ),
        "final_task_id": final_task["task_id"],
        "final_decision": final_task.get("decision"),
    }


def capture_case(
    base_url: str,
    spec: dict[str, Any],
    questions: dict[str, dict[str, Any]],
    output_root: Path,
    timeout_seconds: int,
    run_suffix: str,
    admin_opener: Any,
    admin_cookies: CookieJar,
) -> None:
    case_root = output_root / spec["case_name"]
    if case_root.exists():
        raise ApiFailure(f"output already exists: {case_root}")
    case_root.mkdir(parents=True)
    username = f"sub{spec['case_id'].split('-')[1].lower()}{run_suffix}"[:32]
    try:
        print(f"  register learner for {spec['case_id']}", flush=True)
        learner_id = register_learner(base_url, username, f"提交测试-{spec['case_name']}")
        context = {key: spec[key] for key in ("education_level", "major", "experience_years", "learning_style", "direction_tags")}
        print("  submit initial context and diagnostic", flush=True)
        api_json(base_url, "PUT", f"/learners/{learner_id}/initial-context", context)
        session = api_json(base_url, "POST", "/diagnostics/sessions", {"learner_id": learner_id, "domain_code": "ai_app_dev", "question_count": 10})
        answers, redacted_answers = diagnostic_answers(session, spec["answer_strategy"], questions)
        api_json(base_url, "POST", f"/diagnostics/sessions/{session['session_id']}/submit", {"learner_id": learner_id, "domain_code": "ai_app_dev", "answers": answers})
        diagnostic = poll_diagnostic(base_url, str(session["session_id"]), learner_id, timeout_seconds)
        profile_id = diagnostic["result"]["profile_id"]
        print("  generate initial learning package", flush=True)
        initial_task = poll_task(base_url, str(api_json(base_url, "POST", "/generation-tasks", {
            "learner_id": learner_id,
            "profile_id": profile_id,
            "trigger_type": "initial_generation",
            "execution_mode": "auto",
            "domain_code": "ai_app_dev",
            "resource_types": list(RESOURCE_TYPES),
            "learning_goal": spec["goal"],
        })["task_id"]), timeout_seconds)
        print(f"  execute {spec['follow_up']} branch", flush=True)
        final_task, feedback = follow_up(
            base_url, spec, learner_id, initial_task, timeout_seconds, questions
        )
        print("  export resources and write evidence", flush=True)
        trace, review = capture_trace(base_url, str(final_task["task_id"]), admin_opener, admin_cookies)
        exports = export_resources(base_url, final_task, case_root / "resource-export")
        write_json(case_root / "case-input.json", {
            "case_id": spec["case_id"], "learner_id": learner_id, "domain_code": "ai_app_dev", "profile_input": context,
            "diagnostic_session_id": session["session_id"], "diagnostic_question_ids": [row["question_id"] for row in redacted_answers],
            "submitted_answers": redacted_answers, "answer_strategy": spec["answer_strategy"], "learning_goal": spec["goal"],
        })
        write_json(case_root / "diagnostic-result.json", concise_diagnostic(diagnostic))
        write_json(case_root / "task-summary.json", {"initial_task": task_summary(initial_task), "final_task": task_summary(final_task)})
        write_json(case_root / "agent-trace-summary.json", trace)
        write_json(case_root / "review-summary.json", review)
        write_json(case_root / "feedback-decision.json", feedback)
        files = [path for path in case_root.rglob("*") if path.is_file() and path.name != "manifest.json"]
        write_json(case_root / "manifest.json", {
            "schema_version": "submission-live-case-v1", "case_id": spec["case_id"], "fixture_version": "ai_app_dev_submission_fixture_v1",
            "captured_at": datetime.now(UTC).isoformat(), "final_task_id": final_task["task_id"], "resource_exports": exports,
            "files": {str(path.relative_to(case_root)).replace("\\", "/"): sha256(path) for path in sorted(files)},
        })
    except Exception:
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture the three real submission demonstration cases.")
    parser.add_argument("--base-url", default="http://localhost:18000/api/v1")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=420)
    parser.add_argument("--admin-username", default=os.environ.get("SUBMISSION_ADMIN_USERNAME", "admin"))
    parser.add_argument("--admin-password", default=os.environ.get("SUBMISSION_ADMIN_PASSWORD"))
    parser.add_argument("--case-id", choices=[item["case_id"] for item in CASE_SPECS])
    args = parser.parse_args()
    if not args.case_id and args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise SystemExit(f"Output directory is not empty: {args.output_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    health = api_json(args.base_url, "GET", "/health/dependencies")
    if not health.get("ready_for_live_demo") or not (health.get("rag") or {}).get("ready"):
        raise SystemExit("Submission environment is not ready for live generation.")
    if not args.admin_password:
        raise SystemExit("Set SUBMISSION_ADMIN_PASSWORD before capturing controlled trace evidence.")
    admin_opener, admin_cookies = admin_session(args.base_url, args.admin_username, args.admin_password)
    questions = fixture_questions()
    run_suffix = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    selected_specs = [item for item in CASE_SPECS if not args.case_id or item["case_id"] == args.case_id]
    for spec in selected_specs:
        print(f"Capturing {spec['case_name']}...", flush=True)
        capture_case(
            args.base_url,
            spec,
            questions,
            args.output_dir,
            args.timeout_seconds,
            run_suffix,
            admin_opener,
            admin_cookies,
        )
    if all((args.output_dir / item["case_name"]).exists() for item in CASE_SPECS):
        write_json(args.output_dir / "README.md", {
            "description": "Three independently created, synthetic learners captured through normal learner, diagnostic, generation, feedback and tutoring APIs.",
            "domain_code": "ai_app_dev", "case_count": len(CASE_SPECS),
        })
    print(json.dumps({"status": "captured", "output_dir": str(args.output_dir), "case_count": len(selected_specs)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
