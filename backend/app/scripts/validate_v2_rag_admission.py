from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from app.rag.candidate_manifest import CandidateIndexManifest, CandidateManifestError


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REPORT_DIR = PROJECT_ROOT / "reports" / "rag_evaluation"
DEFAULT_MANIFEST_PATH = (
    PROJECT_ROOT / "storage" / "candidate-index" / "ai_app_dev" / "manifest.json"
)
DEFAULT_V1_REGRESSION_PATH = (
    PROJECT_ROOT / "reports" / "v2_admission" / "v1-non-live-regression.json"
)
DEFAULT_CONTRACT_BASELINE_PATH = (
    PROJECT_ROOT / "reports" / "v2_admission" / "contract-baseline.json"
)
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "reports" / "v2_admission"

REPORT_FILES = {
    "development": "v2-candidate-full-development.json",
    "acceptance": "v2-candidate-full-acceptance.json",
    "all": "v2-candidate-full-all.json",
}
IDENTITY_FIELDS = (
    "embedding_model",
    "algorithm_version",
    "index_version",
    "source_data_version",
    "acceptance_cases_sha256",
)
REQUIRED_TARGET_CHECKS = (
    "recall_at_12",
    "priority_top_12_coverage",
    "prerequisite_coverage",
    "source_completeness",
    "cross_domain_errors",
    "p95_latency_ms",
    "v2_contract_illegal_outputs",
)


@dataclass(frozen=True, slots=True)
class AdmissionPaths:
    development: Path
    acceptance: Path
    all_cases: Path
    manifest: Path
    v1_regression: Path
    contract_baseline: Path

    @classmethod
    def defaults(cls) -> "AdmissionPaths":
        return cls(
            development=DEFAULT_REPORT_DIR / REPORT_FILES["development"],
            acceptance=DEFAULT_REPORT_DIR / REPORT_FILES["acceptance"],
            all_cases=DEFAULT_REPORT_DIR / REPORT_FILES["all"],
            manifest=DEFAULT_MANIFEST_PATH,
            v1_regression=DEFAULT_V1_REGRESSION_PATH,
            contract_baseline=DEFAULT_CONTRACT_BASELINE_PATH,
        )


def _load_json(path: Path, *, label: str, errors: list[str]) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"missing_{label}:{path}")
        return None
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"invalid_{label}:{type(exc).__name__}")
        return None
    if not isinstance(payload, dict):
        errors.append(f"invalid_{label}:not_an_object")
        return None
    return payload


def _check(checks: list[dict[str, Any]], check_id: str, passed: bool, detail: str) -> bool:
    checks.append({"id": check_id, "passed": passed, "detail": detail})
    return passed


def _report_shape_is_valid(
    report: dict[str, Any] | None,
    *,
    expected_split: str,
    expected_case_count: int,
    checks: list[dict[str, Any]],
) -> bool:
    if report is None:
        return _check(checks, f"report_{expected_split}", False, "report is unavailable")
    passed = (
        report.get("engine") == "v2-candidate"
        and report.get("mode") == "full"
        and report.get("split") == expected_split
        and report.get("case_count") == expected_case_count
    )
    return _check(
        checks,
        f"report_{expected_split}",
        passed,
        "requires V2 candidate, full mode, expected split, and expected case count",
    )


def _acceptance_targets_pass(
    report: dict[str, Any] | None, checks: list[dict[str, Any]]
) -> bool:
    target_checks = report.get("target_checks") if report else None
    passed = isinstance(target_checks, dict) and all(
        target_checks.get(key) is True for key in REQUIRED_TARGET_CHECKS
    )
    return _check(
        checks,
        "acceptance_targets",
        passed,
        "all frozen-acceptance V2 target checks must be true",
    )


def _report_identity_is_consistent(
    reports: dict[str, dict[str, Any] | None], checks: list[dict[str, Any]]
) -> bool:
    available = [report for report in reports.values() if report is not None]
    if len(available) != 3:
        return _check(
            checks,
            "report_identity",
            False,
            "development, acceptance, and all reports are required",
        )
    differences = [
        field
        for field in IDENTITY_FIELDS
        if len({str(report.get(field)) for report in available}) != 1
    ]
    return _check(
        checks,
        "report_identity",
        not differences,
        "consistent fields: " + (", ".join(differences) if differences else "all"),
    )


def _all_report_is_aggregate(
    reports: dict[str, dict[str, Any] | None], checks: list[dict[str, Any]]
) -> bool:
    development, acceptance, all_cases = (
        reports["development"],
        reports["acceptance"],
        reports["all"],
    )
    if any(report is None for report in (development, acceptance, all_cases)):
        return _check(checks, "all_report_aggregate", False, "all three reports are required")
    assert development is not None and acceptance is not None and all_cases is not None
    metric_keys = (
        "recall_at_12",
        "priority_top_12_coverage",
        "prerequisite_coverage",
        "source_completeness",
    )
    try:
        metrics_match = all(
            int(all_cases["metrics"][key]["numerator"])
            == int(development["metrics"][key]["numerator"])
            + int(acceptance["metrics"][key]["numerator"])
            and int(all_cases["metrics"][key]["denominator"])
            == int(development["metrics"][key]["denominator"])
            + int(acceptance["metrics"][key]["denominator"])
            for key in metric_keys
        )
        count_matches = int(all_cases["case_count"]) == int(development["case_count"]) + int(
            acceptance["case_count"]
        )
    except (KeyError, TypeError, ValueError):
        metrics_match = count_matches = False
    return _check(
        checks,
        "all_report_aggregate",
        metrics_match and count_matches,
        "all report must be the offline aggregate of development and frozen acceptance",
    )


def _manifest_matches_reports(
    manifest_payload: dict[str, Any] | None,
    reports: dict[str, dict[str, Any] | None],
    checks: list[dict[str, Any]],
    collection_metadata_reader: Callable[[str], dict[str, Any] | None] | None,
) -> CandidateIndexManifest | None:
    if manifest_payload is None:
        _check(checks, "candidate_manifest", False, "candidate manifest is unavailable")
        return None
    try:
        manifest = CandidateIndexManifest.from_dict(manifest_payload)
    except (CandidateManifestError, TypeError) as exc:
        _check(checks, "candidate_manifest", False, f"invalid manifest: {exc}")
        return None
    report = reports["acceptance"]
    if report is None:
        _check(checks, "candidate_manifest", False, "acceptance report is unavailable")
        return None
    matches = (
        manifest.domain_code == "ai_app_dev"
        and manifest.index_version == report.get("index_version")
        and manifest.embedding_model == report.get("embedding_model")
        and manifest.source_data_version == report.get("source_data_version")
        and bool(manifest.active_collection.strip())
    )
    _check(
        checks,
        "candidate_manifest",
        matches,
        "active collection manifest must match report index, model, data version, and domain",
    )
    if collection_metadata_reader is None:
        _check(
            checks,
            "active_collection_metadata",
            False,
            "no read-only collection metadata reader was provided",
        )
        return manifest
    try:
        metadata = collection_metadata_reader(manifest.active_collection)
    except Exception as exc:  # The reader is an integration boundary.
        metadata = None
        detail = f"collection metadata unavailable: {type(exc).__name__}"
    else:
        detail = "active collection metadata matches manifest and report"
    collection_matches = isinstance(metadata, dict) and all(
        metadata.get(key) == expected
        for key, expected in (
            ("index_version", manifest.index_version),
            ("embedding_model", manifest.embedding_model),
            ("source_data_version", manifest.source_data_version),
            ("domain_code", manifest.domain_code),
        )
    )
    _check(checks, "active_collection_metadata", collection_matches, detail)
    return manifest


def _v1_regression_passes(
    evidence: dict[str, Any] | None, checks: list[dict[str, Any]]
) -> bool:
    command = str(evidence.get("command", "")) if evidence else ""
    passed = bool(
        evidence
        and evidence.get("schema_version") == "v1-non-live-regression-v1"
        and evidence.get("status") == "passed"
        and int(evidence.get("failed", 1)) == 0
        and "pytest tests/contracts tests/unit tests/integration" in command
        and "not live" in command
    )
    return _check(
        checks,
        "v1_non_live_regression",
        passed,
        "recorded V1 regression must be passed and use the required non-live command",
    )


def _contract_baseline_is_approved(
    evidence: dict[str, Any] | None, checks: list[dict[str, Any]]
) -> bool:
    passed = bool(
        evidence
        and evidence.get("schema_version") == "v2-contract-baseline-attestation-v1"
        and evidence.get("status") == "approved"
        and str(evidence.get("approved_by", "")).strip()
        and str(evidence.get("baseline_ref", "")).strip()
    )
    return _check(
        checks,
        "contract_baseline",
        passed,
        "contract maintainer approval or an independently verified baseline is required",
    )


def validate_v2_rag_admission(
    paths: AdmissionPaths | None = None,
    *,
    collection_metadata_reader: Callable[[str], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Validate evidence only; it never embeds, writes a database, or switches a collection."""
    paths = paths or AdmissionPaths.defaults()
    errors: list[str] = []
    checks: list[dict[str, Any]] = []
    reports = {
        "development": _load_json(paths.development, label="development_report", errors=errors),
        "acceptance": _load_json(paths.acceptance, label="acceptance_report", errors=errors),
        "all": _load_json(paths.all_cases, label="all_report", errors=errors),
    }
    manifest_payload = _load_json(paths.manifest, label="candidate_manifest", errors=errors)
    v1_evidence = _load_json(paths.v1_regression, label="v1_regression", errors=errors)
    contract_evidence = _load_json(
        paths.contract_baseline, label="contract_baseline", errors=errors
    )

    _report_shape_is_valid(reports["development"], expected_split="development", expected_case_count=30, checks=checks)
    _report_shape_is_valid(reports["acceptance"], expected_split="acceptance", expected_case_count=20, checks=checks)
    _report_shape_is_valid(reports["all"], expected_split="all", expected_case_count=50, checks=checks)
    _acceptance_targets_pass(reports["acceptance"], checks)
    _report_identity_is_consistent(reports, checks)
    _all_report_is_aggregate(reports, checks)
    manifest = _manifest_matches_reports(
        manifest_payload, reports, checks, collection_metadata_reader
    )
    _v1_regression_passes(v1_evidence, checks)
    _contract_baseline_is_approved(contract_evidence, checks)

    rag_admitted = not errors and all(check["passed"] for check in checks)
    blockers = [
        {"id": check["id"], "detail": check["detail"]}
        for check in checks
        if not check["passed"]
    ]
    blockers.extend({"id": error.split(":", 1)[0], "detail": error} for error in errors)
    # A full V2 chain is intentionally absent in stage five; never imply a runtime switch.
    runtime_blockers = [
        *blockers,
        {
            "id": "v2_agent_chain_incomplete",
            "detail": "Profile, Generation, Review, Orchestrator, and Tutoring have no approved V2 runtime chain.",
        },
        {
            "id": "v2_graph_e2e_not_approved",
            "detail": "V2 graph, run-summary, SSE-summary, and human-recovery end-to-end tests are not approved.",
        },
    ]
    identity = {
        field: reports["acceptance"].get(field)
        for field in IDENTITY_FIELDS
        if reports["acceptance"] is not None
    }
    return {
        "schema_version": "v2-rag-integration-admission-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "rag_admission_status": "rag_admitted" if rag_admitted else "rag_admission_blocked",
        "runtime_cutover_status": "runtime_cutover_blocked",
        "checks": checks,
        "blockers": blockers,
        "runtime_cutover_blockers": runtime_blockers,
        "identity": identity,
        "candidate_manifest": (
            {
                "active_collection": manifest.active_collection,
                "index_version": manifest.index_version,
                "embedding_model": manifest.embedding_model,
                "source_data_version": manifest.source_data_version,
            }
            if manifest is not None
            else None
        ),
        "evidence_paths": {
            "development": str(paths.development),
            "acceptance": str(paths.acceptance),
            "all": str(paths.all_cases),
            "manifest": str(paths.manifest),
            "v1_regression": str(paths.v1_regression),
            "contract_baseline": str(paths.contract_baseline),
        },
    }


def markdown_report(result: dict[str, Any]) -> str:
    lines = [
        "# V2 RAG Integration Admission",
        "",
        f"- RAG 准入：`{result['rag_admission_status']}`",
        f"- 统一 V2 运行链切换：`{result['runtime_cutover_status']}`",
        f"- 生成时间：{result['generated_at']}",
        "",
        "| 检查 | 结果 | 说明 |",
        "|---|---|---|",
    ]
    for check in result["checks"]:
        lines.append(
            f"| {check['id']} | {'passed' if check['passed'] else 'blocked'} | {check['detail']} |"
        )
    lines.extend(["", "## 阻塞项", ""])
    blockers = result["runtime_cutover_blockers"]
    for blocker in blockers:
        lines.append(f"- `{blocker['id']}`：{blocker['detail']}")
    if result["candidate_manifest"]:
        manifest = result["candidate_manifest"]
        lines.extend(
            [
                "",
                "## Candidate Evidence",
                "",
                f"- Active collection：`{manifest['active_collection']}`",
                f"- Index version：`{manifest['index_version']}`",
            ]
        )
    return "\n".join(lines) + "\n"


def _chroma_metadata_reader(collection_name: str) -> dict[str, Any] | None:
    # Import lazily so unit tests and report-only checks need no Chroma client construction.
    from app.rag.vector_store import VectorStore

    collection = VectorStore().client.get_collection(name=collection_name)
    return dict(collection.metadata or {})


def write_admission_result(result: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "v2-rag-integration-admission.json"
    markdown_path = output_dir / "v2-rag-integration-admission.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(markdown_report(result), encoding="utf-8")
    return json_path, markdown_path


def main() -> None:
    defaults = AdmissionPaths.defaults()
    parser = argparse.ArgumentParser(description="Read-only V2 RAG integration admission check.")
    parser.add_argument("--development", type=Path, default=defaults.development)
    parser.add_argument("--acceptance", type=Path, default=defaults.acceptance)
    parser.add_argument("--all-report", type=Path, default=defaults.all_cases)
    parser.add_argument("--manifest", type=Path, default=defaults.manifest)
    parser.add_argument("--v1-regression", type=Path, default=defaults.v1_regression)
    parser.add_argument("--contract-baseline", type=Path, default=defaults.contract_baseline)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = validate_v2_rag_admission(
        AdmissionPaths(
            development=args.development,
            acceptance=args.acceptance,
            all_cases=args.all_report,
            manifest=args.manifest,
            v1_regression=args.v1_regression,
            contract_baseline=args.contract_baseline,
        ),
        collection_metadata_reader=_chroma_metadata_reader,
    )
    if not args.no_write:
        write_admission_result(result, args.output_dir)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            f"RAG={result['rag_admission_status']}; "
            f"runtime={result['runtime_cutover_status']}."
        )


if __name__ == "__main__":
    main()
