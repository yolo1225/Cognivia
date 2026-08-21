from __future__ import annotations

import argparse
import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.agents.retrieval_agent import KnowledgeRetrievalAgent
from app.rag.candidate_manifest import CandidateManifestStore
from app.rag.vector_store import VectorStore
from app.scripts.validate_rag_evaluation import (
    DEFAULT_DATA_DIR,
    DEFAULT_KNOWLEDGE_PATH,
    load_evaluation_data,
    materialize_retrieve_input,
    validate_rag_evaluation,
)
from app.scripts.validate_rag_seed import load_knowledge_items

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REPORT_DIR = PROJECT_ROOT / "reports" / "rag_evaluation"
ENGINE_NAME = "candidate-rag"
ALGORITHM_VERSION = "candidate-rag-v5.0"
CANDIDATE_MODES = ("full", "semantic-only", "explicit-only", "semantic+relation")
TARGETS = {
    "recall_at_12": 0.90,
    "priority_top_12_coverage": 0.95,
    "prerequisite_coverage": 0.90,
    "source_completeness": 1.0,
    "cross_domain_errors": 0,
    "p95_latency_ms": 3000,
    "contract_illegal_outputs": 0,
}


def _ratio(numerator: int, denominator: int) -> dict[str, int | float | None]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "ratio": round(numerator / denominator, 6) if denominator else None,
    }


def _percentile(values: list[float], quantile: float) -> float | None:
    return (
        round(sorted(values)[max(0, math.ceil(len(values) * quantile) - 1)], 3) if values else None
    )


def _checks(metrics: dict[str, Any]) -> dict[str, bool]:
    return {
        "recall_at_12": (metrics["recall_at_12"]["ratio"] or 0) >= TARGETS["recall_at_12"],
        "priority_top_12_coverage": (metrics["priority_top_12_coverage"]["ratio"] or 0)
        >= TARGETS["priority_top_12_coverage"],
        "prerequisite_coverage": (metrics["prerequisite_coverage"]["ratio"] or 0)
        >= TARGETS["prerequisite_coverage"],
        "source_completeness": (metrics["source_completeness"]["ratio"] or 0)
        == TARGETS["source_completeness"],
        "cross_domain_errors": metrics["cross_domain_errors"] == 0,
        "p95_latency_ms": (metrics["latency_ms"]["p95"] or math.inf) <= TARGETS["p95_latency_ms"],
        "contract_illegal_outputs": metrics["contract_illegal_outputs"] == 0,
    }


def _attribution(output: Any, missing: set[str], source_incomplete: bool) -> list[str]:
    warnings = set(output.warnings)
    if not output.query_text.strip():
        return ["query"]
    if source_incomplete or any(
        value.startswith("candidate_missing_source:") for value in warnings
    ):
        return ["source"]
    if any(
        value.startswith(("candidate_", "explicit_knowledge_unavailable:")) for value in warnings
    ):
        return ["index"]
    return ["ranking"] if missing else []


def evaluate_candidate_cases(
    cases: list[dict[str, Any]],
    agent: Any,
    *,
    split: str,
    knowledge_ids: set[str],
    knowledge_version: str,
    acceptance_hash: str,
    embedding_model: str,
    index_version: str,
    mode: str,
) -> dict[str, Any]:
    counts = {
        key: 0
        for key in (
            "recall_num",
            "recall_den",
            "priority_num",
            "priority_den",
            "prereq_num",
            "prereq_den",
            "source_num",
            "source_den",
            "illegal",
        )
    }
    cross_domain_errors = 0
    latencies: list[float] = []
    failed = {
        key: []
        for key in (
            "recall_at_12",
            "priority",
            "prerequisite",
            "source_completeness",
            "cross_domain",
            "contract_illegal_outputs",
        )
    }
    results: list[dict[str, Any]] = []
    for case in cases:
        started = time.perf_counter()
        try:
            output, error = agent.execute(materialize_retrieve_input(case, "ai_app_dev")), None
        except Exception as exc:
            output, error = None, type(exc).__name__
        elapsed = (time.perf_counter() - started) * 1000
        latencies.append(elapsed)
        gold = {str(item["knowledge_id"]) for item in case["gold_knowledge"]}
        priority = set(case["retrieval_plan"]["priority_knowledge_ids"])
        prerequisite = set(case["retrieval_plan"]["prerequisite_knowledge_ids"])
        retrieved = [] if output is None else [item.knowledge_id for item in output.chunks]
        result_ids = set(retrieved)
        counts["recall_num"] += len(gold & result_ids)
        counts["recall_den"] += len(gold)
        counts["priority_num"] += len(priority & result_ids)
        counts["priority_den"] += len(priority)
        counts["prereq_num"] += len(prerequisite & result_ids)
        counts["prereq_den"] += len(prerequisite)
        source_complete = output is not None and all(
            item.source.source_title and item.source.license_note for item in output.chunks
        )
        counts["source_num"] += len(retrieved) if source_complete else 0
        counts["source_den"] += len(retrieved)
        cross_domain = bool(result_ids - knowledge_ids)
        cross_domain_errors += int(cross_domain)
        counts["illegal"] += int(error is not None)
        missing = gold - result_ids
        failures = []
        for name, condition in (
            ("recall_at_12", bool(missing)),
            ("priority", bool(priority - result_ids)),
            ("prerequisite", bool(prerequisite - result_ids)),
            ("source_completeness", not source_complete),
            ("cross_domain", cross_domain),
            ("contract_illegal_outputs", error is not None),
        ):
            if condition:
                failed[name].append(case["case_id"])
                failures.append(name)
        results.append(
            {
                "case_id": case["case_id"],
                "latency_ms": round(elapsed, 3),
                "gold_knowledge_ids": sorted(gold),
                "retrieved_knowledge_ids": retrieved,
                "failures": failures,
                "failure_attributions": ["contract"]
                if error
                else _attribution(output, missing, not source_complete),
                "error": error,
            }
        )
    metrics = {
        "recall_at_12": _ratio(counts["recall_num"], counts["recall_den"]),
        "priority_top_12_coverage": _ratio(counts["priority_num"], counts["priority_den"]),
        "prerequisite_coverage": _ratio(counts["prereq_num"], counts["prereq_den"]),
        "source_completeness": _ratio(counts["source_num"], counts["source_den"]),
        "cross_domain_errors": cross_domain_errors,
        "contract_illegal_outputs": counts["illegal"],
        "latency_ms": {"p50": _percentile(latencies, 0.5), "p95": _percentile(latencies, 0.95)},
    }
    return {
        "status": "passed" if all(_checks(metrics).values()) else "failed",
        "engine": ENGINE_NAME,
        "algorithm_version": ALGORITHM_VERSION,
        "mode": mode,
        "split": split,
        "generated_at": datetime.now(UTC).isoformat(),
        "case_count": len(cases),
        "embedding_model": embedding_model,
        "index_version": index_version,
        "knowledge_source_version": knowledge_version,
        "acceptance_cases_sha256": acceptance_hash,
        "metrics": metrics,
        "target_checks": _checks(metrics),
        "failed_case_ids": failed,
        "cases": results,
    }


def _markdown_report(result: dict[str, Any]) -> str:
    metrics = result["metrics"]
    lines = [
        "# Candidate RAG Evaluation",
        "",
        f"- Candidate 索引版本：`{result['index_version']}`",
        f"- Embedding 模型：`{result['embedding_model']}`",
        f"- 案例数：{result['case_count']}",
        "",
        "| 指标 | 值 |",
        "| --- | --- |",
    ]
    for key in (
        "recall_at_12",
        "priority_top_12_coverage",
        "prerequisite_coverage",
        "source_completeness",
    ):
        value = metrics[key]
        lines.append(f"| {key} | {value['numerator']}/{value['denominator']} ({value['ratio']}) |")
    lines.extend(
        [
            f"| cross_domain_errors | {metrics['cross_domain_errors']} |",
            f"| contract_illegal_outputs | {metrics['contract_illegal_outputs']} |",
            f"| p95_latency_ms | {metrics['latency_ms']['p95']} |",
            "",
            f"结论：{'通过' if result['status'] == 'passed' else '未通过'}",
        ]
    )
    return "\n".join(lines) + "\n"


def write_report(
    result: dict[str, Any], output_dir: Path = DEFAULT_REPORT_DIR
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"candidate-rag-{result['mode']}-{result['split']}"
    json_path, markdown_path = output_dir / f"{stem}.json", output_dir / f"{stem}.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(_markdown_report(result), encoding="utf-8")
    return json_path, markdown_path


def aggregate_candidate_reports(
    development: dict[str, Any], acceptance: dict[str, Any]
) -> dict[str, Any]:
    if (
        development["engine"] != ENGINE_NAME
        or acceptance["engine"] != ENGINE_NAME
        or development["index_version"] != acceptance["index_version"]
    ):
        raise ValueError("candidate reports must use one engine and index version")
    metrics: dict[str, Any] = {}
    for key in (
        "recall_at_12",
        "priority_top_12_coverage",
        "prerequisite_coverage",
        "source_completeness",
    ):
        left, right = development["metrics"][key], acceptance["metrics"][key]
        metrics[key] = _ratio(
            left["numerator"] + right["numerator"], left["denominator"] + right["denominator"]
        )
    p95s = [
        item["metrics"]["latency_ms"]["p95"]
        for item in (development, acceptance)
        if item["metrics"]["latency_ms"]["p95"] is not None
    ]
    metrics.update(
        {
            "cross_domain_errors": development["metrics"]["cross_domain_errors"]
            + acceptance["metrics"]["cross_domain_errors"],
            "contract_illegal_outputs": development["metrics"]["contract_illegal_outputs"]
            + acceptance["metrics"]["contract_illegal_outputs"],
            "latency_ms": {"p50": None, "p95": max(p95s) if p95s else None},
        }
    )
    failed = {
        key: sorted(
            set(
                development["failed_case_ids"].get(key, [])
                + acceptance["failed_case_ids"].get(key, [])
            )
        )
        for key in TARGETS
    }
    return {
        **development,
        "status": "aggregated",
        "split": "all",
        "case_count": development["case_count"] + acceptance["case_count"],
        "metrics": metrics,
        "target_checks": _checks(metrics),
        "failed_case_ids": failed,
        "cases": [*development["cases"], *acceptance["cases"]],
    }


def _collection_exists(client: Any, name: str) -> bool:
    try:
        client.get_collection(name=name)
    except Exception:
        return False
    return True


def run_candidate_evaluation(
    *,
    split: str,
    mode: str,
    data_dir: Path = DEFAULT_DATA_DIR,
    knowledge_path: Path = DEFAULT_KNOWLEDGE_PATH,
) -> dict[str, Any]:
    datasets, metadata = load_evaluation_data(data_dir)
    validation = validate_rag_evaluation(data_dir, knowledge_path)
    manifest = CandidateManifestStore().load(
        "ai_app_dev", collection_exists=lambda name: _collection_exists(VectorStore().client, name)
    )
    if manifest is None:
        raise RuntimeError("candidate manifest is missing")
    with KnowledgeRetrievalAgent.production(mode=mode) as agent:
        return evaluate_candidate_cases(
            datasets[split],
            agent,
            split=split,
            knowledge_ids={
                str(item["knowledge_id"]) for item in load_knowledge_items(knowledge_path)
            },
            knowledge_version=validation["source_data_version"],
            acceptance_hash=metadata["manifest"]["acceptance_cases_sha256"],
            embedding_model=manifest.embedding_model,
            index_version=manifest.index_version,
            mode=mode,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the active candidate RAG index.")
    parser.add_argument("--mode", choices=CANDIDATE_MODES, default="full")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--split", choices=("development", "acceptance"), required=True)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--knowledge-path", type=Path, default=DEFAULT_KNOWLEDGE_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not args.live:
        parser.error("--live is required; candidate RAG never falls back to mock embeddings")
    result = run_candidate_evaluation(
        split=args.split, mode=args.mode, data_dir=args.data_dir, knowledge_path=args.knowledge_path
    )
    write_report(result, args.output_dir)
    print(
        json.dumps(result, ensure_ascii=False, indent=2) if args.json else _markdown_report(result)
    )


if __name__ == "__main__":
    main()
