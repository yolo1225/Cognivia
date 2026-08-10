from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.agents.contract_examples import (
    feedback_flow_example,
    human_review_example,
    initial_generation_flow_example,
    resource_examples,
)
from app.agents.contracts import (
    ExecutionMode,
    FinalizeTaskInput,
    HumanDecision,
    HumanReviewInput,
    ResourceType,
    ReviewDecision,
    ReviewIssue,
    ReviewIssueCode,
    TaskDecision,
)
from app.agents.v2_orchestrator_agent import (
    HumanReviewSubmission,
    V2OrchestratorAgent,
    V2OrchestratorError,
)


class StubHumanReviewProvider:
    def __init__(self, decision: HumanDecision) -> None:
        self.decision = decision

    def get_submission(self, _request: HumanReviewInput) -> HumanReviewSubmission:
        return HumanReviewSubmission(
            decision=self.decision,
            review_comment="管理员已核对审核证据。",
            operator_id="admin_demo",
            reviewed_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
        )


class FailingHumanReviewProvider:
    def get_submission(self, _request: HumanReviewInput) -> HumanReviewSubmission:
        raise RuntimeError("provider unavailable")


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
    return report.model_copy(
        update={
            "resource_type": resource_type,
            "decision": decision,
            "passed": decision == ReviewDecision.PASSED,
            "manual_review_required": decision == ReviewDecision.MANUAL_REVIEW_REQUIRED,
            "issues": [] if decision == ReviewDecision.PASSED else [_revision_issue()],
        }
    )


def test_prepare_routes_initial_and_feedback_tasks() -> None:
    agent = V2OrchestratorAgent()
    initial = initial_generation_flow_example()["prepare_task"]["input"]
    feedback = feedback_flow_example()["prepare_task"]["input"]

    initial_output = agent.execute(initial)
    feedback_output = agent.execute(feedback)

    assert initial_output.next_node == "analyze_profile"
    assert feedback_output.next_node == "interpret_feedback"
    assert initial_output.contract_version == "agent-contract-v2"
    assert initial_output.task_id == initial_output.context.task_id


def test_finalize_completes_auto_mode_and_requires_review_in_assisted_mode() -> None:
    agent = V2OrchestratorAgent()
    request = _generation_finalize_input()

    completed = agent.execute(request)
    assisted = agent.execute(
        request.model_copy(
            update={
                "context": request.context.model_copy(
                    update={"execution_mode": ExecutionMode.ASSISTED}
                )
            }
        )
    )

    assert completed.decision == TaskDecision.COMPLETED
    assert completed.passed_resource_types == [ResourceType.LECTURE]
    assert assisted.decision == TaskDecision.MANUAL_REVIEW_REQUIRED
    assert assisted.manual_review_required


def test_finalize_prioritizes_manual_review_and_rejection() -> None:
    agent = V2OrchestratorAgent()
    request = _generation_finalize_input()
    report = request.review_reports[0]

    manual = agent.execute(
        request.model_copy(
            update={
                "review_reports": [
                    _report_with_decision(report, ReviewDecision.MANUAL_REVIEW_REQUIRED)
                ]
            }
        )
    )
    rejected = agent.execute(
        request.model_copy(
            update={
                "review_reports": [_report_with_decision(report, ReviewDecision.REJECTED)]
            }
        )
    )

    assert manual.decision == TaskDecision.MANUAL_REVIEW_REQUIRED
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
    output = V2OrchestratorAgent().execute(
        request.model_copy(
            update={"review_reports": [revision_report], "revision_count": current_count}
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

    output = V2OrchestratorAgent().execute(request)

    assert output.passed_resource_types == [ResourceType.LECTURE]
    assert output.revision_plan is not None
    assert output.revision_plan.resource_types == [ResourceType.PRACTICE_GUIDE]


def test_finalize_returns_no_change_for_non_generation_tutoring_result() -> None:
    request = feedback_flow_example()["finalize_task"]["input"]

    output = V2OrchestratorAgent().execute(request)

    assert output.decision == TaskDecision.NO_CHANGE
    assert not output.manual_review_required


@pytest.mark.parametrize(
    ("human_decision", "expected"),
    [
        (HumanDecision.APPROVE, TaskDecision.COMPLETED),
        (HumanDecision.REQUEST_REVISION, TaskDecision.REVISION_REQUIRED),
        (HumanDecision.REJECT, TaskDecision.REJECTED),
    ],
)
def test_finalize_human_decision_overrides_model_review(
    human_decision: HumanDecision,
    expected: TaskDecision,
) -> None:
    request = _generation_finalize_input().model_copy(
        update={"human_decision": human_decision}
    )

    output = V2OrchestratorAgent().execute(request)

    assert output.decision == expected
    if human_decision == HumanDecision.REQUEST_REVISION:
        assert output.passed_resource_types == []
        assert output.revision_plan is not None
        assert output.revision_plan.resource_types == [ResourceType.LECTURE]


@pytest.mark.parametrize("decision", list(HumanDecision))
def test_human_review_maps_administrator_submission(decision: HumanDecision) -> None:
    request = human_review_example()["human_review"]["input"]
    agent = V2OrchestratorAgent(StubHumanReviewProvider(decision))

    output = agent.execute(request)

    expected = {
        HumanDecision.APPROVE: TaskDecision.COMPLETED,
        HumanDecision.REQUEST_REVISION: TaskDecision.REVISION_REQUIRED,
        HumanDecision.REJECT: TaskDecision.REJECTED,
    }[decision]
    assert output.decision == decision
    assert output.task_decision == expected
    assert output.task_id == request.task_id


def test_human_review_rejects_disallowed_decision_and_provider_failure() -> None:
    request = human_review_example()["human_review"]["input"].model_copy(
        update={"allowed_decisions": [HumanDecision.APPROVE]}
    )
    with pytest.raises(V2OrchestratorError, match="human_review_decision_not_allowed"):
        V2OrchestratorAgent(StubHumanReviewProvider(HumanDecision.REJECT)).execute(request)
    with pytest.raises(V2OrchestratorError, match="human_review_provider_failed"):
        V2OrchestratorAgent(FailingHumanReviewProvider()).execute(request)


def test_human_review_requires_provider() -> None:
    request = human_review_example()["human_review"]["input"]
    with pytest.raises(V2OrchestratorError, match="human_review_provider_not_configured"):
        V2OrchestratorAgent().execute(request)


def test_orchestrator_rejects_non_contract_input() -> None:
    with pytest.raises(V2OrchestratorError, match="invalid_orchestrator_input_type"):
        V2OrchestratorAgent().execute({})  # type: ignore[arg-type]


def test_v2_orchestrator_module_has_no_legacy_dependency() -> None:
    imported = __import__("app.agents.v2_orchestrator_agent", fromlist=["*"])
    source = __import__("inspect").getsource(imported)
    assert "legacy_contracts" not in source
    assert "legacy_state" not in source
    assert "BaseAgent" not in source
