"""Standalone V2 Orchestrator Agent with deterministic task decisions."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Protocol, overload

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agents.contracts import (
    ExecutionMode,
    FinalizeTaskInput,
    FinalizeTaskOutput,
    HumanDecision,
    HumanReviewInput,
    HumanReviewOutput,
    PrepareTaskInput,
    PrepareTaskOutput,
    ResourceType,
    ReviewDecision,
    ReviewIssueCode,
    RevisionPlan,
    TaskContext,
    TaskDecision,
    TriggerType,
)


ORCHESTRATOR_AGENT_NAME = "orchestrator_agent_v2"
SYSTEM_PROMPT = (
    "你是 V2 协调编排智能体。只负责触发类型路由、审核结果汇总、修订次数控制和"
    "人工复核决定映射。不得生成或改写教学内容，不得替管理员作出人工决定。"
)


class V2OrchestratorError(RuntimeError):
    """Controlled error raised at the V2 orchestration boundary."""


class HumanReviewSubmission(BaseModel):
    """Out-of-band administrator input supplied when a human-review node resumes."""

    model_config = ConfigDict(extra="forbid")

    decision: HumanDecision
    review_comment: str = Field(min_length=1, max_length=2000)
    operator_id: str = Field(min_length=1, max_length=64)
    reviewed_at: datetime


class HumanReviewProvider(Protocol):
    def get_submission(self, request: HumanReviewInput) -> HumanReviewSubmission: ...


class V2OrchestratorAgent:
    """Formal V2 boundary for prepare, finalize, and human-review decisions."""

    name = ORCHESTRATOR_AGENT_NAME
    system_prompt = SYSTEM_PROMPT

    def __init__(
        self,
        human_review_provider: HumanReviewProvider | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._human_review_provider = human_review_provider
        self._logger = logger or logging.getLogger(__name__)

    @overload
    def execute(self, request: PrepareTaskInput) -> PrepareTaskOutput: ...

    @overload
    def execute(self, request: FinalizeTaskInput) -> FinalizeTaskOutput: ...

    @overload
    def execute(self, request: HumanReviewInput) -> HumanReviewOutput: ...

    def execute(
        self,
        request: PrepareTaskInput | FinalizeTaskInput | HumanReviewInput,
    ) -> PrepareTaskOutput | FinalizeTaskOutput | HumanReviewOutput:
        try:
            if isinstance(request, PrepareTaskInput):
                output = self._prepare_task(request)
            elif isinstance(request, FinalizeTaskInput):
                output = self._finalize_task(request)
            elif isinstance(request, HumanReviewInput):
                output = self._human_review(request)
            else:
                self._logger.warning(
                    "orchestrator_rejected error_code=invalid_orchestrator_input_type"
                )
                raise V2OrchestratorError("invalid_orchestrator_input_type")
        except V2OrchestratorError:
            raise
        except ValidationError as exc:
            self._log_failure(request, "invalid_orchestrator_output")
            raise V2OrchestratorError("invalid_orchestrator_output") from exc
        except Exception as exc:
            self._log_failure(request, "orchestrator_execution_failed")
            raise V2OrchestratorError("orchestrator_execution_failed") from exc

        self._log_success(output)
        return output

    def _prepare_task(self, request: PrepareTaskInput) -> PrepareTaskOutput:
        validated = PrepareTaskInput.model_validate(request.model_dump(mode="python"))
        context = TaskContext.model_validate(validated.request.model_dump(mode="python"))
        next_node = (
            "interpret_feedback"
            if context.trigger_type == TriggerType.RESOURCE_FEEDBACK
            else "analyze_profile"
        )
        return PrepareTaskOutput(
            task_id=validated.task_id,
            context=context,
            next_node=next_node,
        )

    def _finalize_task(self, request: FinalizeTaskInput) -> FinalizeTaskOutput:
        validated = FinalizeTaskInput.model_validate(request.model_dump(mode="python"))
        passed_types = _passed_resource_types(validated)

        if validated.human_decision is not None:
            return self._finalize_human_decision(validated, passed_types)

        reports = validated.review_reports
        if any(
            report.manual_review_required
            or report.decision == ReviewDecision.MANUAL_REVIEW_REQUIRED
            for report in reports
        ):
            return _finalize_output(
                validated,
                decision=TaskDecision.MANUAL_REVIEW_REQUIRED,
                passed_resource_types=passed_types,
                reason="审核分歧尚未解决，任务进入人工复核。",
            )

        if any(report.decision == ReviewDecision.REJECTED for report in reports):
            return _finalize_output(
                validated,
                decision=TaskDecision.REJECTED,
                passed_resource_types=passed_types,
                reason="至少一份资源被审核拒绝，禁止发布。",
            )

        if reports and all(report.passed for report in reports):
            if validated.context.execution_mode == ExecutionMode.ASSISTED:
                return _finalize_output(
                    validated,
                    decision=TaskDecision.MANUAL_REVIEW_REQUIRED,
                    passed_resource_types=passed_types,
                    reason="辅助审批模式要求管理员确认后才能完成任务。",
                )
            return _finalize_output(
                validated,
                decision=TaskDecision.COMPLETED,
                passed_resource_types=passed_types,
                reason="所有资源均通过双通道审核。",
            )

        if any(report.decision == ReviewDecision.REVISION_REQUIRED for report in reports):
            return self._revision_or_failure(validated, passed_types)

        if (
            not validated.resources
            and not reports
            and validated.tutoring_result is not None
            and not validated.tutoring_result.needs_generation
        ):
            return _finalize_output(
                validated,
                decision=TaskDecision.NO_CHANGE,
                reason="导学判断无需生成资源，保留当前画像与学习内容。",
            )

        return _finalize_output(
            validated,
            decision=TaskDecision.FAILED,
            passed_resource_types=passed_types,
            reason="任务缺少可完成决策所需的生成或审核结果。",
        )

    def _finalize_human_decision(
        self,
        request: FinalizeTaskInput,
        passed_types: list[ResourceType],
    ) -> FinalizeTaskOutput:
        if request.human_decision == HumanDecision.APPROVE:
            approved_types = list(dict.fromkeys(resource.resource_type for resource in request.resources))
            return _finalize_output(
                request,
                decision=TaskDecision.COMPLETED,
                passed_resource_types=approved_types,
                reason="管理员人工复核后批准资源。",
            )
        if request.human_decision == HumanDecision.REJECT:
            return _finalize_output(
                request,
                decision=TaskDecision.REJECTED,
                passed_resource_types=passed_types,
                reason="管理员人工复核后驳回资源。",
            )
        return self._revision_or_failure(request, [], force_all=True)

    def _revision_or_failure(
        self,
        request: FinalizeTaskInput,
        passed_types: list[ResourceType],
        *,
        force_all: bool = False,
    ) -> FinalizeTaskOutput:
        if request.revision_count >= 2:
            return _finalize_output(
                request,
                decision=TaskDecision.FAILED,
                passed_resource_types=passed_types,
                reason="自动修订次数已达到上限 2 次。",
            )

        next_count = request.revision_count + 1
        revision_plan = _build_revision_plan(
            request,
            revision_count=next_count,
            force_all=force_all,
        )
        reason = (
            "管理员要求修订资源。"
            if request.human_decision == HumanDecision.REQUEST_REVISION
            else "审核发现可修订问题，重新检索并生成受影响资源。"
        )
        return FinalizeTaskOutput(
            task_id=request.task_id,
            decision=TaskDecision.REVISION_REQUIRED,
            revision_count=next_count,
            revision_plan=revision_plan,
            passed_resource_types=passed_types,
            manual_review_required=False,
            decision_reason=reason,
        )

    def _human_review(self, request: HumanReviewInput) -> HumanReviewOutput:
        validated = HumanReviewInput.model_validate(request.model_dump(mode="python"))
        if self._human_review_provider is None:
            raise V2OrchestratorError("human_review_provider_not_configured")
        try:
            submission = HumanReviewSubmission.model_validate(
                self._human_review_provider.get_submission(validated)
            )
        except ValidationError as exc:
            raise V2OrchestratorError("invalid_human_review_submission") from exc
        except V2OrchestratorError:
            raise
        except Exception as exc:
            raise V2OrchestratorError("human_review_provider_failed") from exc

        if submission.decision not in validated.allowed_decisions:
            raise V2OrchestratorError("human_review_decision_not_allowed")
        task_decision = {
            HumanDecision.APPROVE: TaskDecision.COMPLETED,
            HumanDecision.REQUEST_REVISION: TaskDecision.REVISION_REQUIRED,
            HumanDecision.REJECT: TaskDecision.REJECTED,
        }[submission.decision]
        return HumanReviewOutput(
            task_id=validated.task_id,
            decision=submission.decision,
            review_comment=submission.review_comment,
            operator_id=submission.operator_id,
            reviewed_at=submission.reviewed_at,
            task_decision=task_decision,
        )

    def _log_success(
        self,
        output: PrepareTaskOutput | FinalizeTaskOutput | HumanReviewOutput,
    ) -> None:
        if isinstance(output, PrepareTaskOutput):
            self._logger.info(
                "orchestrator_prepared task_id=%s next_node=%s",
                output.task_id,
                output.next_node,
            )
        elif isinstance(output, FinalizeTaskOutput):
            self._logger.info(
                "orchestrator_finalized task_id=%s decision=%s revision_count=%s "
                "resource_types=%s",
                output.task_id,
                output.decision,
                output.revision_count,
                output.passed_resource_types,
            )
        else:
            self._logger.info(
                "orchestrator_human_reviewed task_id=%s decision=%s operator_id=%s",
                output.task_id,
                output.decision,
                output.operator_id,
            )

    def _log_failure(
        self,
        request: PrepareTaskInput | FinalizeTaskInput | HumanReviewInput | object,
        error_code: str,
    ) -> None:
        self._logger.warning(
            "orchestrator_failed task_id=%s error_code=%s",
            getattr(request, "task_id", "unknown"),
            error_code,
        )


def _passed_resource_types(request: FinalizeTaskInput) -> list[ResourceType]:
    return list(
        dict.fromkeys(report.resource_type for report in request.review_reports if report.passed)
    )


def _finalize_output(
    request: FinalizeTaskInput,
    *,
    decision: TaskDecision,
    reason: str,
    passed_resource_types: list[ResourceType] | None = None,
) -> FinalizeTaskOutput:
    return FinalizeTaskOutput(
        task_id=request.task_id,
        decision=decision,
        revision_count=request.revision_count,
        passed_resource_types=passed_resource_types or [],
        manual_review_required=decision == TaskDecision.MANUAL_REVIEW_REQUIRED,
        decision_reason=reason,
    )


def _build_revision_plan(
    request: FinalizeTaskInput,
    *,
    revision_count: int,
    force_all: bool,
) -> RevisionPlan:
    selected_reports = [
        report
        for report in request.review_reports
        if force_all or report.decision == ReviewDecision.REVISION_REQUIRED
    ]
    resource_types = list(dict.fromkeys(report.resource_type for report in selected_reports))
    if not resource_types:
        resource_types = list(
            dict.fromkeys(resource.resource_type for resource in request.resources)
        )

    issue_codes: list[ReviewIssueCode] = []
    query_terms: list[str] = []
    required_changes: list[str] = []
    for report in selected_reports:
        for issue in report.issues:
            issue_codes.append(issue.code)
            query_terms.extend(issue.knowledge_ids)
            required_changes.append(issue.suggested_revision)

    if request.context.learning_goal:
        query_terms.append(request.context.learning_goal)
    if not required_changes:
        required_changes.append("根据审核结论修订受影响资源并重新验证来源、难度和知识覆盖。")
    if not query_terms:
        query_terms.extend(resource_type.value for resource_type in resource_types)

    return RevisionPlan(
        revision_count=revision_count,
        resource_types=list(dict.fromkeys(resource_types)),
        issue_codes=list(dict.fromkeys(issue_codes)),
        query_terms=list(dict.fromkeys(query_terms))[:30],
        required_changes=list(dict.fromkeys(required_changes))[:30],
    )
