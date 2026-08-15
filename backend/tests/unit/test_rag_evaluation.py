from __future__ import annotations

import json
from copy import deepcopy
import shutil
from pathlib import Path

import pytest

from app.scripts.evaluate_rag import (
    _markdown_report,
    aggregate_candidate_reports,
    evaluate_candidate_cases,
)
from app.agents.contracts import RetrieveKnowledgeOutput, RetrievedChunk, RetrievalMatchType, RetrievalPurpose, SourceRef
from app.scripts.validate_rag_evaluation import (
    DEFAULT_DATA_DIR,
    DEFAULT_KNOWLEDGE_PATH,
    RagEvaluationValidationError,
    canonical_cases_sha256,
    load_evaluation_data,
    materialize_retrieve_input,
    validate_rag_evaluation,
)
from app.scripts.validate_rag_seed import load_knowledge_items


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _copy_dataset(tmp_path: Path) -> Path:
    target = tmp_path / "rag_evaluation"
    shutil.copytree(DEFAULT_DATA_DIR, target)
    return target


def test_rag_gold_dataset_is_valid_and_complete() -> None:
    result = validate_rag_evaluation()

    assert result["status"] == "passed"
    assert result["total_case_count"] == 50
    assert result["covered_knowledge_count"] == 50
    assert result["splits"]["development"]["case_count"] == 30
    assert result["splits"]["acceptance"]["case_count"] == 20
    assert result["splits"]["development"]["hidden_answer_cases"] >= 12
    assert result["splits"]["acceptance"]["hidden_answer_cases"] >= 8


def test_all_cases_materialize_as_frozen_retrieval_inputs() -> None:
    datasets, metadata = load_evaluation_data()

    for cases in datasets.values():
        for case in cases:
            contract = materialize_retrieve_input(case, "ai_app_dev")
            assert contract.task_id == case["case_id"]
            assert contract.context.domain_code == "ai_app_dev"
            assert contract.retrieval_plan.n_results == 12
    assert metadata["manifest"]["acceptance_case_count"] == 20


def test_acceptance_content_change_breaks_frozen_hash(tmp_path: Path) -> None:
    data_dir = _copy_dataset(tmp_path)
    path = data_dir / "acceptance_cases.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["cases"][0]["query"] += "（已篡改）"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with pytest.raises(RagEvaluationValidationError, match="frozen acceptance content hash"):
        validate_rag_evaluation(data_dir)


def test_hidden_gold_cannot_leak_into_explicit_input(tmp_path: Path) -> None:
    data_dir = _copy_dataset(tmp_path)
    path = data_dir / "development_cases.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    case = next(
        item
        for item in payload["cases"]
        if any(label["input_role"] == "none" for label in item["gold_knowledge"])
    )
    hidden = next(
        label["knowledge_id"]
        for label in case["gold_knowledge"]
        if label["input_role"] == "none"
    )
    case["retrieval_plan"]["priority_knowledge_ids"].append(hidden)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with pytest.raises(RagEvaluationValidationError, match="hidden gold leaked"):
        validate_rag_evaluation(data_dir)


def test_canonical_case_hash_does_not_depend_on_file_order() -> None:
    datasets, _ = load_evaluation_data()
    cases = datasets["acceptance"]

    assert canonical_cases_sha256(cases) == canonical_cases_sha256(list(reversed(cases)))


def test_rag_dataset_is_isolated_from_existing_p0_loader_directory() -> None:
    p0_path = PROJECT_ROOT / "data" / "evaluation_cases" / "p0_cases.json"
    p0_payload = json.loads(p0_path.read_text(encoding="utf-8"))
    manifest = json.loads((p0_path.parent / "manifest.json").read_text(encoding="utf-8"))
    loaded_p0_cases = []
    for file_name in manifest.get("legacy_files", []):
        path = p0_path.parent / file_name
        payload = json.loads(path.read_text(encoding="utf-8"))
        loaded_p0_cases.extend(payload.get("cases", []))

    assert len(p0_payload["cases"]) == 50
    assert len(loaded_p0_cases) == 50
    assert manifest["active_file"] == "v3/p0_cases.json"
    assert DEFAULT_DATA_DIR.parent != p0_path.parent


def test_candidate_evaluation_records_contract_and_index_metadata() -> None:
    datasets, metadata = load_evaluation_data()
    case = next(
        item for item in datasets["development"] if item["retrieval_plan"]["priority_knowledge_ids"]
    )
    knowledge_id = case["retrieval_plan"]["priority_knowledge_ids"][0]

    class StubAgent:
        def execute(self, request):
            return RetrieveKnowledgeOutput(
                task_id=request.task_id,
                query_text="validated candidate query",
                chunks=[
                    RetrievedChunk(
                        chunk_id=f"{knowledge_id}::chunk::0",
                        knowledge_id=knowledge_id,
                        name="Knowledge",
                        category="RAG",
                        difficulty=2,
                        content="Traceable evidence",
                        similarity=0.75,
                        matched_by=RetrievalMatchType.PRIORITY,
                        used_for=RetrievalPurpose.REMEDIAL_EXPLANATION,
                        source=SourceRef(
                            source_ref_id=f"{knowledge_id}::chunk::0",
                            knowledge_id=knowledge_id,
                            source_title="Official source",
                            source_url="https://example.com/source",
                            license_note="Official documentation",
                        ),
                    )
                ],
                covered_knowledge_ids=[knowledge_id],
            )

    items = load_knowledge_items(DEFAULT_KNOWLEDGE_PATH)
    result = evaluate_candidate_cases(
        [case],
        StubAgent(),
        split="development",
        knowledge_ids={item["knowledge_id"] for item in items},
        knowledge_version="test-version",
        acceptance_hash=metadata["manifest"]["acceptance_cases_sha256"],
        embedding_model="test-embedding",
        index_version="test-index",
        mode="full",
    )

    assert result["engine"] == "candidate-rag"
    assert result["metrics"]["contract_illegal_outputs"] == 0
    assert result["index_version"] == "test-index"


def test_candidate_report_renders_metadata_and_failure_attribution() -> None:
    datasets, metadata = load_evaluation_data()
    case = datasets["development"][0]

    class EmptyAgent:
        def execute(self, request):
            return RetrieveKnowledgeOutput(
                task_id=request.task_id,
                query_text="deterministic evaluation query",
                chunks=[],
                covered_knowledge_ids=[],
                warnings=["explicit_knowledge_unavailable:missing"],
            )

    result = evaluate_candidate_cases(
        [case],
        EmptyAgent(),
        split="development",
        knowledge_ids={item["knowledge_id"] for item in load_knowledge_items(DEFAULT_KNOWLEDGE_PATH)},
        knowledge_version="test-version",
        acceptance_hash=metadata["manifest"]["acceptance_cases_sha256"],
        embedding_model="test-embedding",
        index_version="test-index",
        mode="full",
    )

    assert "index" in result["cases"][0]["failure_attributions"]
    markdown = _markdown_report(result)
    assert "# Candidate RAG Evaluation" in markdown
    assert "Candidate 索引版本：`test-index`" in markdown
    assert "contract_illegal_outputs" in markdown


def test_aggregate_candidate_reports_preserves_frozen_run_metadata() -> None:
    datasets, metadata = load_evaluation_data()
    case = next(
        item
        for item in datasets["development"]
        if item["retrieval_plan"]["priority_knowledge_ids"]
    )
    knowledge_id = case["retrieval_plan"]["priority_knowledge_ids"][0]

    class PriorityOnlyAgent:
        def execute(self, request):
            return RetrieveKnowledgeOutput(
                task_id=request.task_id,
                query_text="aggregated V3 query",
                chunks=[
                    RetrievedChunk(
                        chunk_id=f"{knowledge_id}::chunk::0",
                        knowledge_id=knowledge_id,
                        name="Knowledge",
                        category="RAG",
                        difficulty=2,
                        content="Traceable evidence",
                        similarity=0.75,
                        matched_by=RetrievalMatchType.PRIORITY,
                        used_for=RetrievalPurpose.REMEDIAL_EXPLANATION,
                        source=SourceRef(
                            source_ref_id=f"{knowledge_id}::chunk::0",
                            knowledge_id=knowledge_id,
                            source_title="Official source",
                            source_url="https://example.com/source",
                            license_note="Official documentation",
                        ),
                    )
                ],
                covered_knowledge_ids=[knowledge_id],
            )

    result = evaluate_candidate_cases(
        [case],
        PriorityOnlyAgent(),
        split="development",
        knowledge_ids={item["knowledge_id"] for item in load_knowledge_items(DEFAULT_KNOWLEDGE_PATH)},
        knowledge_version="test-version",
        acceptance_hash=metadata["manifest"]["acceptance_cases_sha256"],
        embedding_model="test-embedding",
        index_version="test-index",
        mode="full",
    )
    acceptance = deepcopy(result)
    acceptance["split"] = "acceptance"
    acceptance["cases"][0]["case_id"] = "RAG-ACC-TEST"
    for values in acceptance["failed_case_ids"].values():
        values[:] = ["RAG-ACC-TEST"]

    aggregate = aggregate_candidate_reports(result, acceptance)

    assert aggregate["status"] == "aggregated"
    assert aggregate["split"] == "all"
    assert aggregate["case_count"] == 2
    assert aggregate["index_version"] == "test-index"
    assert aggregate["metrics"]["recall_at_12"]["denominator"] == 2 * result["metrics"]["recall_at_12"]["denominator"]
