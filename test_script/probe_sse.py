"""Probe the V2 SSE stream for one live initial-generation task."""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

from run_live import _api_json


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_STEPS = [
    "prepare_task",
    "analyze_profile",
    "retrieve_knowledge",
    "generate_resource",
    "review_resource",
    "finalize_task",
]


def _events(url: str, timeout_seconds: int):
    deadline = time.monotonic() + timeout_seconds
    event_name = "message"
    data: list[str] = []
    with urlopen(Request(url, headers={"Accept": "text/event-stream"}), timeout=timeout_seconds) as response:
        for raw_line in response:
            if time.monotonic() > deadline:
                raise TimeoutError("SSE stream did not reach a terminal event")
            line = raw_line.decode("utf-8").rstrip("\r\n")
            if not line:
                if data:
                    yield event_name, json.loads("\n".join(data))
                event_name, data = "message", []
            elif line.startswith("event: "):
                event_name = line.removeprefix("event: ")
            elif line.startswith("data: "):
                data.append(line.removeprefix("data: "))


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate V2 agent SSE ordering with a live task.")
    parser.add_argument("--base-url", default="http://localhost:8000/api/v1")
    parser.add_argument("--timeout-seconds", type=int, default=360)
    args = parser.parse_args()

    health = _api_json(args.base_url, "GET", "/health/dependencies")
    if not health.get("ready_for_live_demo"):
        raise SystemExit("backend is not ready for a live SSE probe")
    created = _api_json(
        args.base_url,
        "POST",
        "/generation-tasks",
        {
            "learner_id": "learner_001",
            "trigger_type": "initial_generation",
            "execution_mode": "auto",
            "resource_types": ["lecture"],
            "learning_goal": "验证 V2 SSE 节点状态、审核摘要和终态事件。",
        },
    )
    task_id = str(created["task_id"])
    completed_steps: list[str] = []
    review_summary: dict = {}
    terminal: dict = {}
    for name, payload in _events(
        f"{args.base_url.rstrip('/')}/generation-tasks/{task_id}/events",
        args.timeout_seconds,
    ):
        if name == "agent_status" and payload.get("status") == "completed":
            step = str(payload.get("step") or "")
            if step and step not in completed_steps:
                completed_steps.append(step)
            if step == "review_resource":
                review_summary = dict(payload.get("payload") or {})
        if name in {"task_completed", "task_failed", "manual_review_required"}:
            terminal = {"event": name, **payload}
            break

    if terminal.get("event") != "task_completed":
        raise SystemExit(f"V2 SSE task did not complete: {terminal}")
    if completed_steps != EXPECTED_STEPS:
        raise SystemExit(f"unexpected V2 SSE node order: {completed_steps}")
    if not review_summary.get("resource_reviews"):
        raise SystemExit("V2 SSE review event lacks compact review evidence")
    report = {
        "task_id": task_id,
        "provider_mode": "live",
        "completed_steps": completed_steps,
        "review_arbitration": review_summary.get("arbitration", []),
        "terminal": terminal,
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    directory = ROOT / "reports" / "preflight"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"sse-probe-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
