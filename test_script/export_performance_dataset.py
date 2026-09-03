"""Export a privacy-safe performance dataset from a completed live evaluation run."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import evaluate as evaluator


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = (
    ROOT / "deliverables" / "competition-initial-review" / "07_测试数据与案例" / "性能测试"
)


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def export_dataset(run_id: str | None, output_dir: Path) -> tuple[Path, Path]:
    cases, knowledge_versions = evaluator.load_cases()
    run = evaluator.load_live_run(run_id)
    run_path = ROOT / "reports" / "evaluation" / "runs" / f"{run['run_id']}.json"
    case_by_id = {str(case["case_id"]): case for case in cases}
    samples: list[dict[str, Any]] = []
    for result in run.get("results", []):
        case = case_by_id.get(str(result.get("case_id")))
        observed = result.get("observed_result") or {}
        if case is None:
            raise ValueError(f"live run contains an unknown case: {result.get('case_id')}")
        samples.append(
            {
                "case_id": case["case_id"],
                "scenario_type": case.get("scenario_type"),
                "profile_type": (case.get("profile_snapshot") or {}).get("profile_type"),
                "resource_type": case.get("resource_type"),
                "task_status": result.get("task_status"),
                "determinable": bool(observed.get("determinable")),
                "provider_mode": observed.get("provider_mode"),
                "end_to_end_latency_ms": observed.get("latency_ms"),
                "trigger_response_ms": observed.get("trigger_response_ms"),
                "agent_latency_ms": observed.get("agent_latency_ms") or {},
                "failure_category": observed.get("failure_category"),
                "failure_code": observed.get("failure_code"),
            }
        )

    merged = evaluator.merge_live_results(cases, run)
    summary = evaluator.evaluate(
        merged, knowledge_versions, run_mode="live", run_metadata=run
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    samples_path = output_dir / "formal-performance-samples.json"
    summary_path = output_dir / "formal-performance-summary.json"
    samples_path.write_text(
        json.dumps(
            {
                "schema_version": "performance-samples-v1",
                "privacy": "synthetic case IDs only; no learner answer, resource body, prompt, or credential",
                "source_run_id": run["run_id"],
                "source_run_sha256": _sha256(run_path),
                "samples": samples,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    summary_path.write_text(
        json.dumps(
            {
                "schema_version": "performance-summary-v1",
                "generated_at": datetime.now(UTC).isoformat(),
                "source_run_id": run["run_id"],
                "source_run_sha256": _sha256(run_path),
                "case_set_sha256": run.get("case_set_sha256"),
                "model_configuration": summary.get("model_configuration"),
                "rag_configuration": summary.get("rag_configuration"),
                "performance_metrics": {
                    "end_to_end_latency_ms": summary["metrics"]["latency_ms"],
                    "trigger_response_ms": summary["metrics"]["trigger_response_ms"],
                    "end_to_end_latency_sla": summary["metrics"]["end_to_end_latency_sla"],
                    "task_success_rate": summary["metrics"]["task_success_rate"],
                    "agent_latency_ms": summary["metrics"]["agent_latency_ms"],
                },
                "quality_metrics": {
                    key: summary["metrics"][key]
                    for key in (
                        "hallucination_rate",
                        "difficulty_match_accuracy",
                        "core_knowledge_coverage",
                        "review_decision_accuracy",
                        "profile_decision_accuracy",
                    )
                },
                "collection_note": (
                    "The source run predates trigger_response_ms collection. "
                    "Its end-to-end latency and task success data are measured; "
                    "trigger response remains uncollected until the next live formal run."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return samples_path, summary_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", help="completed live run ID; latest is used when omitted")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    samples_path, summary_path = export_dataset(args.run_id, args.output_dir)
    print(json.dumps({"samples": str(samples_path), "summary": str(summary_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
