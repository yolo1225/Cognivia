from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agents.contracts import (
    AgentContractSchema,
    CONTRACT_VERSION,
    GenerationPackageQuality,
    ResourceQualityMetrics,
    ReviewDecision,
    TaskDecision,
)
from app.agents.graphs import build_learning_graph


def test_v8_preserves_review_decisions_and_graph_topology() -> None:
    assert CONTRACT_VERSION == "agent-contract-v8"
    assert "manual_review_required" not in {item.value for item in ReviewDecision}
    assert "manual_review_required" not in {item.value for item in TaskDecision}
    graph = build_learning_graph()
    assert "human_review_node" not in graph.get_graph().nodes


def test_v8_expands_the_complete_evidence_pipeline_to_eighteen_chunks() -> None:
    definitions = AgentContractSchema.model_json_schema()["$defs"]

    assert definitions["RetrievalPlan"]["properties"]["n_results"]["maximum"] == 18
    assert definitions["RetrieveKnowledgeOutput"]["properties"]["chunks"]["maxItems"] == 18
    assert (
        definitions["GenerateResourceInput"]["properties"]["retrieved_chunks"][
            "maxItems"
        ]
        == 18
    )
    assert definitions["ReviewResourceInput"]["properties"]["evidence"]["maxItems"] == 18


@pytest.mark.parametrize(
    ("claims", "hallucinations", "rate", "passed"),
    [(40, 1, 2.5, True), (20, 1, 5.0, False)],
)
def test_package_hallucination_threshold_is_strict(
    claims: int, hallucinations: int, rate: float, passed: bool
) -> None:
    metrics = GenerationPackageQuality(
        evaluated_claim_count=claims,
        contradicted_claim_count=hallucinations,
        evidence_insufficient_claim_count=0,
        unresolved_claim_count=0,
        verifiable_claim_count=claims,
        hallucinated_claim_count=hallucinations,
        hallucination_rate=rate,
        difficulty_match_score=85,
        covered_core_knowledge_count=9,
        target_core_knowledge_count=10,
        core_knowledge_coverage=90,
        passed=passed,
        revision_count=0,
    )
    assert metrics.passed is passed


def test_evidence_insufficient_claims_stay_in_rate_denominator_and_block_publish() -> None:
    metrics = GenerationPackageQuality(
        evaluated_claim_count=8,
        contradicted_claim_count=1,
        evidence_insufficient_claim_count=7,
        unresolved_claim_count=0,
        verifiable_claim_count=8,
        hallucinated_claim_count=1,
        hallucination_rate=12.5,
        difficulty_match_score=90,
        covered_core_knowledge_count=10,
        target_core_knowledge_count=10,
        core_knowledge_coverage=100,
        passed=False,
        revision_count=0,
    )

    assert metrics.hallucination_rate == 12.5
    assert metrics.passed is False


def test_quality_metrics_reject_model_supplied_inconsistent_ratios() -> None:
    with pytest.raises(ValidationError, match="derived from claim counts"):
        ResourceQualityMetrics(
            evaluated_claim_count=40,
            contradicted_claim_count=1,
            evidence_insufficient_claim_count=0,
            unresolved_claim_count=0,
            verifiable_claim_count=40,
            hallucinated_claim_count=1,
            hallucination_rate=1,
            difficulty_match_score=85,
            covered_core_knowledge_count=9,
            target_core_knowledge_count=10,
            core_knowledge_coverage=90,
            passed=True,
        )


def test_resource_quality_defers_coverage_threshold_to_package_scope() -> None:
    metrics = ResourceQualityMetrics(
        evaluated_claim_count=10,
        contradicted_claim_count=0,
        evidence_insufficient_claim_count=0,
        unresolved_claim_count=0,
        verifiable_claim_count=10,
        hallucinated_claim_count=0,
        hallucination_rate=0,
        difficulty_match_score=80,
        covered_core_knowledge_count=9,
        target_core_knowledge_count=10,
        core_knowledge_coverage=90,
        passed=True,
    )

    assert metrics.passed


def test_package_quality_has_competition_metric_shape() -> None:
    value = GenerationPackageQuality(
        evaluated_claim_count=60,
        contradicted_claim_count=1,
        evidence_insufficient_claim_count=0,
        unresolved_claim_count=0,
        verifiable_claim_count=60,
        hallucinated_claim_count=1,
        hallucination_rate=1.67,
        difficulty_match_score=90,
        covered_core_knowledge_count=18,
        target_core_knowledge_count=20,
        core_knowledge_coverage=90,
        passed=True,
        revision_count=1,
    )
    assert value.passed
