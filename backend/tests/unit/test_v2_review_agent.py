from __future__ import annotations

import threading

import pytest

from app.agents.contract_examples import initial_generation_flow_example
from app.agents.contracts import (
    FactCheck,
    ModelReview,
    ReviewCriterionScores,
    ReviewDecision,
    ReviewResourceInput,
)
from app.agents.v2_review_agent import (
    V2ReviewError,
    V2ReviewValidationAgent,
    _adapt_model_review_payload,
    _cross_validate,
    _review_decision,
    _reviews_disagree,
)


class DeterministicChannel:
    def review(self, *, deterministic_review, **_kwargs):
        return deterministic_review


class PersistentConflictChannel:
    def __init__(self) -> None:
        self.calls = 0
        self._lock = threading.Lock()

    def review(self, *, role, model, deterministic_review, **_kwargs):
        with self._lock:
            self.calls += 1
        passed = role == "primary_review_model"
        value = 96 if passed else 60
        return ModelReview(
            model_role=role,
            model_name=model or role,
            scores=ReviewCriterionScores(
                factual_accuracy=value,
                source_traceability=value,
                difficulty_match=value,
                core_knowledge_coverage=value,
            ),
            passed=passed,
            fact_checks=deterministic_review.fact_checks,
        )


def _input() -> ReviewResourceInput:
    return initial_generation_flow_example()["review_resource"]["input"]


def test_v2_review_emits_dual_model_contract_report() -> None:
    output = V2ReviewValidationAgent(channel=DeterministicChannel()).execute(_input())

    report = output.reports[0]
    assert output.contract_version == "agent-contract-v2"
    assert report.primary_review.model_role == "primary_review_model"
    assert report.secondary_review.model_role == "secondary_review_model"
    assert report.decision in {ReviewDecision.PASSED, ReviewDecision.REVISION_REQUIRED}
    assert not report.arbitration.required


def test_v2_review_rechecks_and_requires_manual_review_for_persistent_conflict() -> None:
    channel = PersistentConflictChannel()
    output = V2ReviewValidationAgent(channel=channel).execute(_input())

    report = output.reports[0]
    assert channel.calls == 4
    assert report.arbitration.required
    assert report.arbitration.retrieval_performed
    assert report.arbitration.primary_recheck is not None
    assert report.arbitration.secondary_recheck is not None
    assert report.arbitration.disagreement_remains
    assert report.decision == ReviewDecision.MANUAL_REVIEW_REQUIRED
    assert report.manual_review_required


def test_v2_review_rejects_non_contract_input() -> None:
    with pytest.raises(V2ReviewError, match="invalid_review_input_type"):
        V2ReviewValidationAgent(channel=DeterministicChannel()).execute({})  # type: ignore[arg-type]


def test_review_provider_adapter_binds_known_metadata_and_normalizes_aliases() -> None:
    payload = _adapt_model_review_payload(
        {
            "review_scores": {
                "accuracy": 95,
                "traceability": 93,
                "difficulty": 90,
                "coverage": 91,
            },
            "passed": True,
            "fact_checks": [
                {
                    "claim": "证据支持该结论",
                    "is_supported": True,
                    "source_ref_ids": "AIAPP-K001::source::0",
                    "reason": "来源直接说明。",
                }
            ],
        },
        role="primary_review_model",
        model_name="qwen-max",
    )
    review = ModelReview.model_validate(payload)

    assert review.model_role == "primary_review_model"
    assert review.model_name == "qwen-max"
    assert review.scores.factual_accuracy == 95
    assert review.fact_checks[0].source_ref_ids == ["AIAPP-K001::source::0"]


def test_unsupported_determinable_fact_cannot_pass_even_with_perfect_scores() -> None:
    request = _input()
    # Build against the frozen example's valid sources so this isolates the model
    # channel's explicit negative fact conclusion from deterministic score checks.
    deterministic = V2ReviewValidationAgent(channel=DeterministicChannel())._review_pair(
        request.resources[0], request, recheck=False
    )[0]
    reviewed = ModelReview(
        model_role="primary_review_model",
        model_name="qwen-max",
        scores=ReviewCriterionScores(
            factual_accuracy=100,
            source_traceability=100,
            difficulty_match=100,
            core_knowledge_coverage=100,
        ),
        passed=True,
        fact_checks=[
            FactCheck(
                claim="一个无法由证据支持的结论。",
                supported=False,
                source_ref_ids=[],
                reason="证据中没有该结论。",
            )
        ],
    )

    validated = _cross_validate(reviewed, deterministic, request)

    assert not validated.passed
    assert validated.scores.factual_accuracy < 85
    assert any(issue.code.value == "unsupported_claim" for issue in validated.issues)


def test_unsupported_fact_difference_requires_arbitration_and_never_passes() -> None:
    request = _input()
    primary, secondary = V2ReviewValidationAgent(
        channel=DeterministicChannel()
    )._review_pair(request.resources[0], request, recheck=False)
    primary = primary.model_copy(
        update={
            "fact_checks": [
                FactCheck(
                    claim="一个无法由证据支持的结论。",
                    supported=False,
                    source_ref_ids=[],
                    reason="证据中没有该结论。",
                )
            ],
            "passed": True,
        }
    )
    primary = _cross_validate(primary, primary, request)

    assert _reviews_disagree(primary, secondary)
    decision = _review_decision(
        primary,
        secondary,
        primary.scores,
        disagreement_remains=False,
    )
    assert decision != ReviewDecision.PASSED


def test_v2_review_module_has_no_legacy_dependency() -> None:
    imported = __import__("app.agents.v2_review_agent", fromlist=["*"])
    source = __import__("inspect").getsource(imported)
    assert "legacy_contracts" not in source
    assert "legacy_state" not in source
