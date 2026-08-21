from __future__ import annotations

import ast
import json
from pathlib import Path

from app.rag.candidate_chunker import CHUNKER_VERSION
from app.rag.candidate_manifest import (
    DISTANCE_METRIC,
    MANIFEST_SCHEMA_VERSION,
    CandidateIndexManifest,
    compute_index_version,
)
from app.scripts.validate_v3_rag_admission import (
    AdmissionPaths,
    markdown_report,
    validate_v3_rag_admission,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _metric(numerator: int = 1, denominator: int = 1) -> dict[str, int | float]:
    return {"numerator": numerator, "denominator": denominator, "ratio": numerator / denominator}


def _manifest_and_identity() -> tuple[CandidateIndexManifest, dict[str, str]]:
    source_version = "sha256:" + "a" * 64
    manifest = CandidateIndexManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        active_collection="knowledge_ai_app_dev_candidate_test",
        previous_collection=None,
        domain_code="ai_app_dev",
        embedding_model="test-embedding",
        embedding_dimensions=3,
        distance_metric=DISTANCE_METRIC,
        chunker_version=CHUNKER_VERSION,
        index_version=compute_index_version(
            domain_code="ai_app_dev",
            source_data_version=source_version,
            embedding_model="test-embedding",
            embedding_dimensions=3,
            distance_metric=DISTANCE_METRIC,
            chunker_version=CHUNKER_VERSION,
        ),
        source_data_version=source_version,
        last_successful_sync_at="2026-07-25T00:00:00+00:00",
        indexed_item_count=50,
        indexed_chunk_count=120,
    )
    return manifest, {
        "embedding_model": manifest.embedding_model,
        "algorithm_version": "v3-candidate-test-1.0",
        "index_version": manifest.index_version,
        "source_data_version": manifest.source_data_version,
        "acceptance_cases_sha256": "sha256:" + "b" * 64,
    }


def _report(split: str, case_count: int, identity: dict[str, str]) -> dict[str, object]:
    return {
        "status": "aggregated" if split == "all" else "evaluated",
        "engine": "v3-candidate",
        "mode": "full",
        "split": split,
        "case_count": case_count,
        **identity,
        "target_checks": {
            "recall_at_12": True,
            "priority_top_12_coverage": True,
            "prerequisite_coverage": True,
            "source_completeness": True,
            "cross_domain_errors": True,
            "p95_latency_ms": True,
            "contract_illegal_outputs": True,
        },
        "metrics": {
            "recall_at_12": _metric(case_count, case_count),
            "priority_top_12_coverage": _metric(case_count, case_count),
            "prerequisite_coverage": _metric(case_count, case_count),
            "source_completeness": _metric(case_count, case_count),
            "cross_domain_errors": 0,
            "contract_illegal_outputs": 0,
            "latency_ms": {"p50": 10.0, "p95": 20.0},
        },
    }


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _evidence_paths(tmp_path: Path) -> tuple[AdmissionPaths, CandidateIndexManifest]:
    manifest, identity = _manifest_and_identity()
    development = _report("development", 30, identity)
    acceptance = _report("acceptance", 20, identity)
    all_cases = _report("all", 50, identity)
    paths = AdmissionPaths(
        development=tmp_path / "development.json",
        acceptance=tmp_path / "acceptance.json",
        all_cases=tmp_path / "all.json",
        manifest=tmp_path / "manifest.json",
        v1_regression=tmp_path / "v1-regression.json",
        contract_baseline=tmp_path / "contract-baseline.json",
    )
    _write_json(paths.development, development)
    _write_json(paths.acceptance, acceptance)
    _write_json(paths.all_cases, all_cases)
    _write_json(paths.manifest, manifest.to_dict())
    _write_json(
        paths.v1_regression,
        {
            "schema_version": "v1-non-live-regression-v1",
            "status": "passed",
            "failed": 0,
            "command": 'pytest tests/contracts tests/unit tests/integration -m "not live"',
        },
    )
    _write_json(
        paths.contract_baseline,
        {
        "schema_version": "v3-contract-baseline-attestation-v1",
            "status": "approved",
            "approved_by": "contract-maintainer",
            "baseline_ref": "origin/main",
        },
    )
    return paths, manifest


def _collection_reader(manifest: CandidateIndexManifest):
    return lambda _: {
        "domain_code": manifest.domain_code,
        "embedding_model": manifest.embedding_model,
        "source_data_version": manifest.source_data_version,
        "index_version": manifest.index_version,
    }


def test_complete_evidence_admits_rag_but_never_runtime_cutover(tmp_path: Path) -> None:
    paths, manifest = _evidence_paths(tmp_path)

    result = validate_v3_rag_admission(
        paths, collection_metadata_reader=_collection_reader(manifest)
    )

    assert result["rag_admission_status"] == "rag_admitted"
    assert result["runtime_cutover_status"] == "runtime_cutover_blocked"
    assert result["blockers"] == []
    assert "rag_admitted" in markdown_report(result)


def test_missing_report_is_rejected(tmp_path: Path) -> None:
    paths, manifest = _evidence_paths(tmp_path)
    paths.acceptance.unlink()

    result = validate_v3_rag_admission(
        paths, collection_metadata_reader=_collection_reader(manifest)
    )

    assert result["rag_admission_status"] == "rag_admission_blocked"
    assert any(blocker["id"] == "report_acceptance" for blocker in result["blockers"])


def test_failed_acceptance_metric_is_rejected(tmp_path: Path) -> None:
    paths, manifest = _evidence_paths(tmp_path)
    report = json.loads(paths.acceptance.read_text(encoding="utf-8"))
    report["target_checks"]["recall_at_12"] = False
    _write_json(paths.acceptance, report)

    result = validate_v3_rag_admission(
        paths, collection_metadata_reader=_collection_reader(manifest)
    )

    assert result["rag_admission_status"] == "rag_admission_blocked"
    assert any(blocker["id"] == "acceptance_targets" for blocker in result["blockers"])


def test_inconsistent_index_or_acceptance_hash_is_rejected(tmp_path: Path) -> None:
    paths, manifest = _evidence_paths(tmp_path)
    acceptance = json.loads(paths.acceptance.read_text(encoding="utf-8"))
    acceptance["index_version"] = "sha256:" + "c" * 64
    _write_json(paths.acceptance, acceptance)

    index_result = validate_v3_rag_admission(
        paths, collection_metadata_reader=_collection_reader(manifest)
    )
    assert index_result["rag_admission_status"] == "rag_admission_blocked"
    assert any(blocker["id"] == "report_identity" for blocker in index_result["blockers"])

    paths, manifest = _evidence_paths(tmp_path)
    acceptance = json.loads(paths.acceptance.read_text(encoding="utf-8"))
    acceptance["acceptance_cases_sha256"] = "sha256:" + "c" * 64
    _write_json(paths.acceptance, acceptance)
    hash_result = validate_v3_rag_admission(
        paths, collection_metadata_reader=_collection_reader(manifest)
    )
    assert hash_result["rag_admission_status"] == "rag_admission_blocked"
    assert any(blocker["id"] == "report_identity" for blocker in hash_result["blockers"])


def test_manifest_pointing_at_wrong_collection_is_rejected(tmp_path: Path) -> None:
    paths, manifest = _evidence_paths(tmp_path)
    wrong_metadata = _collection_reader(manifest)(manifest.active_collection)
    wrong_metadata["index_version"] = "sha256:" + "d" * 64

    result = validate_v3_rag_admission(
        paths, collection_metadata_reader=lambda _: wrong_metadata
    )

    assert result["rag_admission_status"] == "rag_admission_blocked"
    assert any(
        blocker["id"] == "active_collection_metadata" for blocker in result["blockers"]
    )


def test_contract_baseline_without_attestation_blocks_rag_admission(tmp_path: Path) -> None:
    paths, manifest = _evidence_paths(tmp_path)
    paths.contract_baseline.unlink()

    result = validate_v3_rag_admission(
        paths, collection_metadata_reader=_collection_reader(manifest)
    )

    assert result["rag_admission_status"] == "rag_admission_blocked"
    assert any(blocker["id"] == "contract_baseline" for blocker in result["blockers"])


def test_v3_graph_runtime_uses_nodes_without_legacy_state() -> None:
    graphs = (PROJECT_ROOT / "backend" / "app" / "agents" / "graphs.py").read_text(
        encoding="utf-8"
    )
    nodes = (PROJECT_ROOT / "backend" / "app" / "agents" / "nodes.py").read_text(
        encoding="utf-8"
    )
    graph_tree = ast.parse(graphs)
    imports = [
        node.module
        for node in ast.walk(graph_tree)
        if isinstance(node, ast.ImportFrom) and node.module
    ]

    assert "app.agents.legacy_state" not in imports
    assert "app.agents.nodes" in imports
    assert "KnowledgeRetrievalAgent" in nodes
