from __future__ import annotations

import pytest

from app.agents.contract_examples import (
    feedback_flow_example,
    initial_generation_flow_example,
    resource_examples,
)
from app.agents.contracts import (
    FinalizeTaskInput,
    ResourceType,
    ReviewDecision,
    ReviewIssue,
    ReviewIssueCode,
    TaskDecision,
)
from app.agents.orchestrator_agent import (
    DETERMINISTIC_CONVERGENCE_MARKER,
    OrchestratorAgent,
    OrchestratorError,
)


def _generation_finalize_input() -> FinalizeTaskInput:
    return initial_generation_flow_example()["finalize_task"]["input"]


def _revision_issue() -> ReviewIssue:
    return ReviewIssue(
        code=ReviewIssueCode.MISSING_KNOWLEDGE,
        section="核心知识",
        knowledge_ids=["AIAPP-K029"],
        description="缺少核心知识说明。",
        suggested_revision="补充核心知识及其来源。",
    )


def _report_with_decision(report, decision: ReviewDecision, resource_type=ResourceType.LECTURE):
    passed = decision == ReviewDecision.PASSED
    return report.model_copy(
        update={
            "resource_type": resource_type,
            "decision": decision,
            "passed": passed,
            "quality_metrics": report.quality_metrics.model_copy(
                update={
                    "evaluated_claim_count": 20,
                    "verifiable_claim_count": 20,
                    "contradicted_claim_count": 0 if passed else 1,
                    "hallucinated_claim_count": 0 if passed else 1,
                    "hallucination_rate": 0 if passed else 5,
                    "passed": passed,
                }
            ),
            "issues": [] if decision == ReviewDecision.PASSED else [_revision_issue()],
        }
    )


def test_prepare_routes_initial_and_feedback_tasks() -> None:
    agent = OrchestratorAgent()
    initial = initial_generation_flow_example()["prepare_task"]["input"]
    feedback = feedback_flow_example()["prepare_task"]["input"]

    initial_output = agent.execute(initial)
    feedback_output = agent.execute(feedback)

    assert initial_output.next_node == "analyze_profile"
    assert feedback_output.next_node == "interpret_feedback"
    assert initial_output.contract_version == "agent-contract-v6"
    assert initial_output.task_id == initial_output.context.task_id


def test_finalize_completes_atomic_package() -> None:
    agent = OrchestratorAgent()
    request = _generation_finalize_input()

    completed = agent.execute(request)
    assert completed.decision == TaskDecision.COMPLETED
    assert set(completed.passed_resource_types) == set(ResourceType)


@pytest.mark.parametrize("resource_count", [1, 2, 3])
def test_finalize_completes_exact_requested_resource_set(resource_count: int) -> None:
    base = _generation_finalize_input()
    request = base.model_copy(
        update={
            "resources": base.resources[:resource_count],
            "review_reports": base.review_reports[:resource_count],
        }
    )

    completed = OrchestratorAgent().execute(request)

    assert completed.decision == TaskDecision.COMPLETED
    assert set(completed.passed_resource_types) == {
        resource.resource_type for resource in request.resources
    }


def test_finalize_fails_when_report_types_do_not_match_requested_resources() -> None:
    base = _generation_finalize_input()
    request = base.model_copy(
        update={
            "resources": base.resources[:2],
            "review_reports": [base.review_reports[0], base.review_reports[2]],
        }
    )

    with pytest.raises(OrchestratorError, match="invalid_orchestrator_output"):
        OrchestratorAgent().execute(request)


def test_finalize_prioritizes_rejection() -> None:
    agent = OrchestratorAgent()
    request = _generation_finalize_input()
    report = request.review_reports[0]

    rejected = agent.execute(
        request.model_copy(
            update={
                "review_reports": [
                    _report_with_decision(report, ReviewDecision.REJECTED),
                    *request.review_reports[1:],
                ]
            }
        )
    )

    assert rejected.decision == TaskDecision.REJECTED


@pytest.mark.parametrize(
    ("current_count", "expected_decision", "expected_count"),
    [
        (0, TaskDecision.REVISION_REQUIRED, 1),
        (1, TaskDecision.REVISION_REQUIRED, 2),
        (2, TaskDecision.FAILED, 2),
    ],
)
def test_finalize_enforces_two_revision_limit(
    current_count: int,
    expected_decision: TaskDecision,
    expected_count: int,
) -> None:
    request = _generation_finalize_input()
    revision_report = _report_with_decision(
        request.review_reports[0], ReviewDecision.REVISION_REQUIRED
    )
    output = OrchestratorAgent().execute(
        request.model_copy(
            update={
                "review_reports": [revision_report, *request.review_reports[1:]],
                "revision_count": current_count,
            }
        )
    )

    assert output.decision == expected_decision
    assert output.revision_count == expected_count
    if expected_decision == TaskDecision.REVISION_REQUIRED:
        assert output.revision_plan is not None
        assert output.revision_plan.resource_types == [ResourceType.LECTURE]
        assert output.revision_plan.issue_codes == [ReviewIssueCode.MISSING_KNOWLEDGE]
        assert "AIAPP-K029" in output.revision_plan.query_terms
        assert "补充核心知识及其来源。" in output.revision_plan.required_changes
    else:
        assert output.revision_plan is None


def test_finalize_allows_one_deterministic_convergence_after_two_revisions() -> None:
    request = _generation_finalize_input()
    report = request.review_reports[0]
    unresolved = report.model_copy(
        update={
            "decision": ReviewDecision.REVISION_REQUIRED,
            "passed": False,
            "issues": [],
            "contradicted_claim_ids": [],
            "undetermined_claim_ids": ["claim_low_risk"],
            "unresolved_claim_ids": [],
            "missing_knowledge_ids": [],
            "quality_metrics": report.quality_metrics.model_copy(
                update={
                    "evidence_insufficient_claim_count": 1,
                    "passed": False,
                    "revision_count": 2,
                }
            ),
        }
    )
    attempt = request.model_copy(
        update={
            "review_reports": [unresolved, *request.review_reports[1:]],
            "revision_count": 2,
        }
    )

    convergence = OrchestratorAgent().execute(attempt)
    exhausted = OrchestratorAgent().execute(
        attempt, deterministic_convergence_attempted=True
    )

    assert convergence.decision is TaskDecision.REVISION_REQUIRED
    assert convergence.revision_count == 2
    assert convergence.revision_plan is not None
    assert DETERMINISTIC_CONVERGENCE_MARKER in convergence.revision_plan.required_changes
    assert exhausted.decision is TaskDecision.FAILED
    assert exhausted.revision_plan is None


def test_finalize_revises_only_resource_causing_package_coverage_failure() -> None:
    request = _generation_finalize_input()
    report = request.review_reports[0]
    target_ids = list(report.target_knowledge_ids)
    missing_id = target_ids[-1]
    covered_ids = target_ids[:-1]
    resource_quality = report.quality_metrics.model_copy(
        update={
            "covered_core_knowledge_count": len(covered_ids),
            "target_core_knowledge_count": len(target_ids),
            "core_knowledge_coverage": round(100 * len(covered_ids) / len(target_ids), 2),
            "passed": True,
        }
    )
    report = report.model_copy(
        update={
            "quality_metrics": resource_quality,
            "covered_knowledge_ids": covered_ids,
            "missing_knowledge_ids": [missing_id],
        }
    )
    package_target_count = request.package_quality.target_core_knowledge_count
    package_covered_count = package_target_count - 1
    package_quality = request.package_quality.model_copy(
        update={
            "covered_core_knowledge_count": package_covered_count,
            "core_knowledge_coverage": round(
                100 * package_covered_count / package_target_count, 2
            ),
            "passed": False,
        }
    )
    failing = request.model_copy(
        update={
            "review_reports": [report, *request.review_reports[1:]],
            "package_passed": False,
            "package_quality": package_quality,
        }
    )

    output = OrchestratorAgent().execute(failing)

    assert output.decision is TaskDecision.REVISION_REQUIRED
    assert output.revision_plan is not None
    assert output.revision_plan.resource_types == [report.resource_type]
    assert output.revision_plan.missing_knowledge_ids_by_resource[report.resource_type] == [
        missing_id
    ]


def test_finalize_preserves_passed_types_and_revises_only_failed_type() -> None:
    base = _generation_finalize_input()
    resources = resource_examples()[:2]
    passed = base.review_reports[0]
    revision = _report_with_decision(
        passed,
        ReviewDecision.REVISION_REQUIRED,
        resource_type=ResourceType.PRACTICE_GUIDE,
    )
    request = base.model_copy(
        update={"resources": resources, "review_reports": [passed, revision]}
    )

    output = OrchestratorAgent().execute(request)

    assert ResourceType.LECTURE in output.passed_resource_types
    assert output.revision_plan is not None
    assert output.revision_plan.resource_types == [ResourceType.PRACTICE_GUIDE]


def test_finalize_returns_no_change_for_non_generation_tutoring_result() -> None:
    request = feedback_flow_example()["finalize_task"]["input"]

    output = OrchestratorAgent().execute(request)

    assert output.decision == TaskDecision.NO_CHANGE


def test_orchestrator_rejects_non_contract_input() -> None:
    with pytest.raises(OrchestratorError, match="invalid_orchestrator_input_type"):
        OrchestratorAgent().execute({})  # type: ignore[arg-type]


def test_v3_orchestrator_module_has_no_legacy_dependency() -> None:
    imported = __import__("app.agents.orchestrator_agent", fromlist=["*"])
    source = __import__("inspect").getsource(imported)
    assert "legacy_contracts" not in source
    assert "legacy_state" not in source
    assert "BaseAgent" not in source
