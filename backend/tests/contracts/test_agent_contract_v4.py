from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agents.contracts import (
    CONTRACT_VERSION,
    GenerationPackageQuality,
    ResourceQualityMetrics,
    ReviewDecision,
    TaskDecision,
)
from app.agents.graphs import build_learning_graph


def test_v5_removes_manual_review_decisions_and_graph_node() -> None:
    assert CONTRACT_VERSION == "agent-contract-v5"
    assert "manual_review_required" not in {item.value for item in ReviewDecision}
    assert "manual_review_required" not in {item.value for item in TaskDecision}
    graph = build_learning_graph()
    assert "human_review_node" not in graph.get_graph().nodes


@pytest.mark.parametrize(
    ("claims", "hallucinations", "rate", "passed"),
    [(40, 1, 2.5, True), (20, 1, 5.0, False)],
)
def test_hallucination_threshold_is_strict(
    claims: int, hallucinations: int, rate: float, passed: bool
) -> None:
    metrics = ResourceQualityMetrics(
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


def test_quality_metrics_reject_model_supplied_inconsistent_ratios() -> None:
    with pytest.raises(ValidationError, match="derived from claim counts"):
        ResourceQualityMetrics(
            verifiable_claim_count=40,
            hallucinated_claim_count=1,
            hallucination_rate=1,
            difficulty_match_score=85,
            covered_core_knowledge_count=9,
            target_core_knowledge_count=10,
            core_knowledge_coverage=90,
            passed=True,
        )


def test_package_quality_has_competition_metric_shape() -> None:
    value = GenerationPackageQuality(
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
