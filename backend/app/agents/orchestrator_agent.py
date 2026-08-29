"""Standalone V10 Orchestrator Agent with deterministic task decisions."""

from __future__ import annotations

import logging
from typing import overload

from pydantic import ValidationError

from app.agents.contracts import (
    FinalizeTaskInput,
    FinalizeTaskOutput,
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
from app.agents.prompt_registry import get_prompt


ORCHESTRATOR_AGENT_NAME = "orchestrator_agent_v3"
SYSTEM_PROMPT = get_prompt("orchestrator")
DETERMINISTIC_CONVERGENCE_MARKER = "[deterministic_convergence_v1]"


class OrchestratorError(RuntimeError):
    """Controlled error raised at the orchestration boundary."""


class OrchestratorAgent:
    """V10 boundary for preparation and deterministic package decisions."""

    name = ORCHESTRATOR_AGENT_NAME
    system_prompt = SYSTEM_PROMPT

    def __init__(
        self,
        logger: logging.Logger | None = None,
    ) -> None:
        self._logger = logger or logging.getLogger(__name__)

    @overload
    def execute(self, request: PrepareTaskInput) -> PrepareTaskOutput: ...

    @overload
    def execute(self, request: FinalizeTaskInput) -> FinalizeTaskOutput: ...

    def execute(
        self,
        request: PrepareTaskInput | FinalizeTaskInput,
        *,
        deterministic_convergence_attempted: bool = False,
    ) -> PrepareTaskOutput | FinalizeTaskOutput:
        try:
            if isinstance(request, PrepareTaskInput):
                output = self._prepare_task(request)
            elif isinstance(request, FinalizeTaskInput):
                output = self._finalize_task(
                    request,
                    deterministic_convergence_attempted=deterministic_convergence_attempted,
                )
            else:
                self._logger.warning(
                    "orchestrator_rejected error_code=invalid_orchestrator_input_type"
                )
                raise OrchestratorError("invalid_orchestrator_input_type")
        except OrchestratorError:
            raise
        except ValidationError as exc:
            self._log_failure(request, "invalid_orchestrator_output")
            raise OrchestratorError("invalid_orchestrator_output") from exc
        except Exception as exc:
            self._log_failure(request, "orchestrator_execution_failed")
            raise OrchestratorError("orchestrator_execution_failed") from exc

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

    def _finalize_task(
        self,
        request: FinalizeTaskInput,
        *,
        deterministic_convergence_attempted: bool,
    ) -> FinalizeTaskOutput:
        validated = FinalizeTaskInput.model_validate(request.model_dump(mode="python"))
        passed_types = _passed_resource_types(validated)

        reports = validated.review_reports
        resource_types = [resource.resource_type for resource in validated.resources]
        report_types = [report.resource_type for report in reports]
        reports_complete = (
            bool(resource_types)
            and len(resource_types) == len(set(resource_types))
            and len(report_types) == len(set(report_types))
            and set(report_types) == set(resource_types)
        )

        if any(report.decision == ReviewDecision.REJECTED for report in reports):
            return _finalize_output(
                validated,
                decision=TaskDecision.REJECTED,
                passed_resource_types=passed_types,
                reason="至少一份资源被审核拒绝，禁止发布。",
            )

        if (
            reports_complete
            and validated.package_quality is not None
            and validated.package_quality.passed
        ):
            return _finalize_output(
                validated,
                decision=TaskDecision.COMPLETED,
                passed_resource_types=passed_types,
                reason="所有资源均通过双通道审核。",
            )

        if (
            validated.package_quality is not None
            and not validated.package_quality.passed
        ):
            return self._revision_or_failure(
                validated,
                passed_types,
                deterministic_convergence_attempted=deterministic_convergence_attempted,
            )

        if reports_complete and validated.package_quality is None:
            return self._revision_or_failure(
                validated,
                passed_types,
                package_failure=True,
                deterministic_convergence_attempted=deterministic_convergence_attempted,
            )

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

    def _revision_or_failure(
        self,
        request: FinalizeTaskInput,
        passed_types: list[ResourceType],
        *,
        force_all: bool = False,
        package_failure: bool = False,
        deterministic_convergence_attempted: bool = False,
    ) -> FinalizeTaskOutput:
        if request.revision_count >= 2:
            eligible_reports = [
                report
                for report in request.review_reports
                if not report.contradicted_claim_ids
                and not report.missing_knowledge_ids
                and report.final_scores.difficulty_match >= 85
                and report.final_scores.core_knowledge_coverage >= 90
                and bool(
                    set(report.undetermined_claim_ids) | set(report.unresolved_claim_ids)
                )
            ]
            if eligible_reports and not deterministic_convergence_attempted:
                plan = _build_revision_plan(
                    request,
                    revision_count=2,
                    force_all=False,
                    package_failure=False,
                )
                plan = plan.model_copy(
                    update={
                        "resource_types": [report.resource_type for report in eligible_reports],
                        "required_changes": [
                            DETERMINISTIC_CONVERGENCE_MARKER,
                            *plan.required_changes,
                        ][:30],
                    }
                )
                return FinalizeTaskOutput(
                    task_id=request.task_id,
                    decision=TaskDecision.REVISION_REQUIRED,
                    revision_count=2,
                    revision_plan=plan,
                    passed_resource_types=passed_types,
                    decision_reason="执行一次低风险未解决声明的确定性安全收敛。",
                )
            return _finalize_output(
                request,
                decision=TaskDecision.FAILED,
                passed_resource_types=[],
                reason="自动定向修订已达到上限 2 次，整包生成失败且不会发布。",
            )

        next_count = request.revision_count + 1
        revision_plan = _build_revision_plan(
            request,
            revision_count=next_count,
            force_all=force_all,
            package_failure=package_failure,
        )
        reason = (
            "资源包难度或唯一知识覆盖未达到比赛门槛，修订受影响资源。"
            if package_failure
            else "审核发现可修订问题，重新检索并生成受影响资源。"
        )
        return FinalizeTaskOutput(
            task_id=request.task_id,
            decision=TaskDecision.REVISION_REQUIRED,
            revision_count=next_count,
            revision_plan=revision_plan,
            passed_resource_types=passed_types,
            decision_reason=reason,
        )

    def _log_success(
        self,
        output: PrepareTaskOutput | FinalizeTaskOutput,
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

    def _log_failure(
        self,
        request: PrepareTaskInput | FinalizeTaskInput | object,
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
        decision_reason=reason,
    )


def _build_revision_plan(
    request: FinalizeTaskInput,
    *,
    revision_count: int,
    force_all: bool,
    package_failure: bool,
) -> RevisionPlan:
    selected_reports = [
        report
        for report in request.review_reports
        if (
            force_all
            or report.decision == ReviewDecision.REVISION_REQUIRED
            or (
                package_failure
                and (
                    bool(report.missing_knowledge_ids)
                    or report.final_scores.difficulty_match < 85
                )
            )
        )
    ]
    resource_types = list(dict.fromkeys(report.resource_type for report in selected_reports))
    if not resource_types:
        resource_types = list(
            dict.fromkeys(resource.resource_type for resource in request.resources)
        )

    issue_codes: list[ReviewIssueCode] = []
    query_terms: list[str] = []
    required_changes: list[str] = []
    missing_by_resource: dict[ResourceType, list[str]] = {}
    preserve_by_resource: dict[ResourceType, list[str]] = {}
    claim_ids_by_resource: dict[ResourceType, list[str]] = {}
    field_paths_by_resource: dict[ResourceType, list[str]] = {}
    for report in selected_reports:
        missing_by_resource[report.resource_type] = report.missing_knowledge_ids
        preserve_by_resource[report.resource_type] = report.covered_knowledge_ids
        affected_claim_ids = list(
            dict.fromkeys(
                [
                    *report.contradicted_claim_ids,
                    *report.undetermined_claim_ids,
                    *report.unresolved_claim_ids,
                ]
            )
        )
        claim_ids_by_resource[report.resource_type] = affected_claim_ids
        latest_review = report.arbitration.primary_recheck or report.primary_review
        checks_by_id = {
            check.claim_id: check for check in latest_review.fact_checks if check.claim_id
        }
        field_paths_by_resource[report.resource_type] = list(
            dict.fromkeys(
                check.field_path
                for claim_id in affected_claim_ids
                if (check := checks_by_id.get(claim_id)) is not None and check.field_path
            )
        )
        query_terms.extend(
            check.claim[:300]
            for claim_id in affected_claim_ids
            if (check := checks_by_id.get(claim_id)) is not None
        )
        query_terms.extend(report.missing_knowledge_ids)
        for issue in report.issues:
            issue_codes.append(issue.code)
            query_terms.extend(issue.knowledge_ids)
            required_changes.append(issue.suggested_revision)
        if affected_claim_ids:
            required_changes.append(
                "优先补检索受影响字段的直接证据；仍无证据时删除冲突或无依据声明，"
                "并将必要步骤改写为不声称具体命令、配置、环境或固定结果的说明性内容。"
            )

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
        missing_knowledge_ids_by_resource=missing_by_resource,
        preserve_knowledge_ids_by_resource=preserve_by_resource,
        claim_ids_by_resource=claim_ids_by_resource,
        field_paths_by_resource=field_paths_by_resource,
    )
