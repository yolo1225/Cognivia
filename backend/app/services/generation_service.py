from sqlalchemy import select, update

from app.agents.contracts import ReviewReport as ContractReviewReport
from app.agents.nodes import GRAPH_STATE
from app.models import (
    GenerationTask,
    KnowledgeUpdateImpact,
    LearnerProfile,
    LearningPackageResource,
    LearningResource,
    ReviewReport,
)
from app.services.learning_package_service import RESOURCE_ORDER, package_member_rows


def _review_status(report: ContractReviewReport) -> str:
    if report.passed:
        return "passed"
    if report.decision.value == "rejected":
        return "failed"
    return "revision_required"


def _source_resources(db, task: GenerationTask) -> dict[str, LearningResource]:
    if task.source_task_id:
        source_task = db.get(GenerationTask, task.source_task_id)
        if source_task is not None:
            return {
                resource.resource_type: resource
                for _member, resource in package_member_rows(db, source_task)
            }
    if task.source_resource_id:
        source = db.get(LearningResource, task.source_resource_id)
        if source is not None:
            return {source.resource_type: source}
    return {}


def _compose_published_package(db, task: GenerationTask) -> None:
    requested_types = set(task.resource_types_json or [])
    generated = list(
        db.scalars(
            select(LearningResource)
            .where(LearningResource.generation_task_id == task.id)
            .order_by(LearningResource.id)
        )
    )
    members: list[LearningPackageResource] = []
    if task.source_task_id:
        source_task = db.get(GenerationTask, task.source_task_id)
        if source_task is not None:
            for source_member, resource in package_member_rows(db, source_task):
                if resource.resource_type in requested_types:
                    continue
                members.append(
                    LearningPackageResource(
                        package_task_id=task.id,
                        resource_id=resource.id,
                        membership_type="inherited",
                        freshness_status=source_member.freshness_status,
                        sort_order=RESOURCE_ORDER.get(resource.resource_type, 99),
                    )
                )
    members.extend(
        LearningPackageResource(
            package_task_id=task.id,
            resource_id=resource.id,
            membership_type="generated",
            freshness_status="current",
            sort_order=RESOURCE_ORDER.get(resource.resource_type, 99),
        )
        for resource in generated
        if resource.resource_type in requested_types and resource.review_status == "passed"
    )
    member_resource_ids = [member.resource_id for member in members]
    member_resources = list(
        db.scalars(
            select(LearningResource).where(LearningResource.id.in_(member_resource_ids))
        )
    )
    if (
        len(member_resource_ids) != len(RESOURCE_ORDER)
        or len(set(member_resource_ids)) != len(member_resource_ids)
        or {resource.resource_type for resource in member_resources} != set(RESOURCE_ORDER)
    ):
        raise ValueError("published_package_members_incomplete")
    existing_resource_ids = set(
        db.scalars(
            select(LearningPackageResource.resource_id).where(
                LearningPackageResource.package_task_id == task.id
            )
        )
    )
    for member in members:
        if member.resource_id not in existing_resource_ids:
            db.add(member)
    db.flush()

    db.execute(
        update(GenerationTask)
        .where(
            GenerationTask.learner_id == task.learner_id,
            GenerationTask.domain_code == task.domain_code,
            GenerationTask.id != task.id,
        )
        .values(is_current_package=False)
    )
    task.is_current_package = True
    if task.source_task_id:
        impact = db.scalar(
            select(KnowledgeUpdateImpact)
            .where(
                KnowledgeUpdateImpact.package_task_id == task.source_task_id,
                KnowledgeUpdateImpact.status == "refreshing",
            )
            .order_by(KnowledgeUpdateImpact.id.desc())
        )
        if impact is not None:
            impact.status = "resolved"
            impact.resolved_by_task_id = task.id
    _recalculate_package_quality(db, task)


def _recalculate_package_quality(db, task: GenerationTask) -> None:
    rows = package_member_rows(db, task)
    resource_ids = [resource.id for _member, resource in rows]
    if not resource_ids:
        return
    reports = list(
        db.scalars(
            select(ReviewReport)
            .where(ReviewReport.resource_id.in_(resource_ids))
            .order_by(ReviewReport.id.desc())
        )
    )
    latest: dict[int, ReviewReport] = {}
    for report in reports:
        latest.setdefault(report.resource_id, report)
    selected = [latest[resource_id] for resource_id in resource_ids if resource_id in latest]
    if len(selected) != len(resource_ids):
        return
    claim_count = sum(item.verifiable_claim_count for item in selected)
    hallucinated = sum(item.hallucinated_claim_count for item in selected)
    target_count = sum(item.target_core_knowledge_count for item in selected)
    covered_count = sum(item.covered_core_knowledge_count for item in selected)
    task.package_quality_json = {
        "verifiable_claim_count": claim_count,
        "hallucinated_claim_count": hallucinated,
        "hallucination_rate": (
            round(100 * hallucinated / claim_count, 2) if claim_count else 0.0
        ),
        "difficulty_match_score": round(
            sum(item.difficulty_match_score for item in selected) / len(selected), 2
        ),
        "covered_core_knowledge_count": covered_count,
        "target_core_knowledge_count": target_count,
        "core_knowledge_coverage": (
            round(100 * covered_count / target_count, 2) if target_count else 100.0
        ),
        "passed": all(item.quality_passed for item in selected),
        "revision_count": max((item.revision_count for item in selected), default=0),
    }


def recover_misclassified_refresh_task(db, task_public_id: str) -> GenerationTask:
    """Publish an already-reviewed refresh that failed only on the legacy three-report rule."""
    task = db.scalar(select(GenerationTask).where(GenerationTask.public_id == task_public_id))
    if task is None:
        raise ValueError("refresh_task_not_found")
    if task.status == "completed" and task.is_current_package:
        return task
    if (
        task.event_type != "knowledge_refresh"
        or not task.source_task_id
        or task.status != "failed"
        or task.failure_reason != "任务缺少可完成决策所需的生成或审核结果。"
    ):
        raise ValueError("refresh_task_not_recoverable")

    source_task = db.get(GenerationTask, task.source_task_id)
    if source_task is None or not source_task.is_current_package:
        raise ValueError("refresh_source_package_not_current")
    requested_types = list(task.resource_types_json or [])
    if not requested_types or len(requested_types) != len(set(requested_types)):
        raise ValueError("refresh_resource_scope_invalid")

    resources = list(
        db.scalars(
            select(LearningResource)
            .where(LearningResource.generation_task_id == task.id)
            .order_by(LearningResource.id)
        )
    )
    if (
        len(resources) != len(requested_types)
        or {resource.resource_type for resource in resources} != set(requested_types)
    ):
        raise ValueError("refresh_generated_resources_incomplete")

    reports = list(
        db.scalars(
            select(ReviewReport)
            .where(ReviewReport.task_id == task.id)
            .order_by(ReviewReport.id.desc())
        )
    )
    latest_reports: dict[int, ReviewReport] = {}
    for report in reports:
        latest_reports.setdefault(report.resource_id, report)
    selected_reports = [latest_reports.get(resource.id) for resource in resources]
    if any(report is None for report in selected_reports):
        raise ValueError("refresh_review_reports_incomplete")
    if any(
        not report.passed
        or not report.quality_passed
        or report.decision != "passed"
        or not (report.primary_review_json or {}).get("passed")
        or not (report.secondary_review_json or {}).get("passed")
        for report in selected_reports
        if report is not None
    ):
        raise ValueError("refresh_review_not_passed")

    impact = db.scalar(
        select(KnowledgeUpdateImpact)
        .where(
            KnowledgeUpdateImpact.package_task_id == source_task.id,
            KnowledgeUpdateImpact.status.in_(["pending", "refreshing"]),
        )
        .order_by(KnowledgeUpdateImpact.id.desc())
    )
    source_resources = _source_resources(db, task)
    expected_affected_ids = {
        source_resources[resource_type].public_id
        for resource_type in requested_types
        if resource_type in source_resources
    }
    if (
        impact is None
        or len(expected_affected_ids) != len(requested_types)
        or not expected_affected_ids.issubset(set(impact.affected_resource_ids_json or []))
    ):
        raise ValueError("refresh_impact_not_recoverable")

    for resource in resources:
        resource.review_status = "passed"
        resource.is_current = True
        previous = source_resources.get(resource.resource_type)
        if previous is not None:
            previous.is_current = False
    task.status = "completed"
    task.progress = 100
    task.decision = "completed"
    task.failure_reason = ""
    coverage = dict(task.package_coverage_json or {})
    coverage["passed"] = not coverage.get("missing_knowledge_ids") and float(
        coverage.get("coverage_score") or 0
    ) >= 90
    task.package_coverage_json = coverage
    _compose_published_package(db, task)
    impact.status = "resolved"
    impact.resolved_by_task_id = task.id
    db.flush()
    return task


def persist_generated_resources(
    db,
    task: GenerationTask,
    profile: LearnerProfile,
    state: GRAPH_STATE,
) -> None:
    profile_payload = profile.ability_profile_json or {}
    source_resources = _source_resources(db, task)
    generation = state.get("generate_resource")
    review = state.get("review_resource")
    finalization = state.get("finalize_task")
    if generation is None or review is None or finalization is None:
        return
    reports = {item.resource_type: item for item in review.reports}
    task.package_coverage_json = {
        "required_knowledge_ids": review.package_required_knowledge_ids,
        "covered_knowledge_ids": review.package_covered_knowledge_ids,
        "missing_knowledge_ids": review.package_missing_knowledge_ids,
        "coverage_score": review.package_coverage_score,
        "passed": review.package_passed,
    }
    task.package_quality_json = review.package_quality.model_dump(mode="json")
    expected_types = set(task.resource_types_json or [])
    report_types = {item.resource_type.value for item in review.reports}
    publish = (
        finalization.decision.value == "completed"
        and report_types == expected_types
        and review.package_quality.passed
        and all(item.passed for item in review.reports)
    )
    existing_resources = {
        item.resource_type: item
        for item in db.query(LearningResource)
        .filter(LearningResource.generation_task_id == task.id)
        .all()
    }
    for artifact in generation.resources:
        draft = artifact
        report = next(
            (item for resource_type, item in reports.items() if resource_type == draft.resource_type),
            None,
        )
        if report is None:
            continue
        previous = source_resources.get(draft.resource_type.value)
        version = (previous.version + 1) if previous else 1
        series_id = (previous.series_id or previous.public_id) if previous else ""
        resource = existing_resources.get(draft.resource_type.value)
        if resource is None:
            resource = LearningResource(
                public_id=f"res_{task.public_id}_{draft.resource_type.value}_v{version}",
                generation_task_id=task.id,
                resource_type=draft.resource_type.value,
                title=draft.structured_content.title,
                content_md=draft.content_md,
                difficulty=draft.difficulty,
                learner_profile_type=profile_payload.get("profile_type", ""),
                sources_json=[
                    source.model_dump(mode="json") for source in draft.source_refs
                ],
                version=version,
                review_status="passed" if publish else "failed",
                series_id=series_id,
                previous_resource_id=previous.id if previous else None,
                is_current=publish,
                adaptation_reason=finalization.decision_reason,
                knowledge_coverage_json=draft.knowledge_coverage,
                structured_content_json=draft.structured_content.model_dump(mode="json"),
            )
            db.add(resource)
            db.flush()
        resource.title = draft.structured_content.title
        resource.content_md = draft.content_md
        resource.difficulty = draft.difficulty
        resource.learner_profile_type = profile_payload.get("profile_type", "")
        resource.sources_json = [
            source.model_dump(mode="json") for source in draft.source_refs
        ]
        resource.review_status = "passed" if publish else "failed"
        resource.is_current = publish
        resource.adaptation_reason = finalization.decision_reason
        resource.knowledge_coverage_json = draft.knowledge_coverage
        resource.structured_content_json = draft.structured_content.model_dump(mode="json")
        if not resource.series_id:
            resource.series_id = resource.public_id
        if publish and previous:
            previous.is_current = False

        stored_report = (
            db.query(ReviewReport)
            .filter(ReviewReport.task_id == task.id)
            .filter(ReviewReport.resource_id == resource.id)
            .one_or_none()
        )
        if stored_report is None:
            stored_report = ReviewReport(resource_id=resource.id, task_id=task.id)
            db.add(stored_report)
        values = dict(
                resource_id=resource.id,
                task_id=task.id,
                primary_review_json=report.primary_review.model_dump(mode="json"),
                secondary_review_json=report.secondary_review.model_dump(mode="json"),
                arbitration_json=report.arbitration.model_dump(mode="json"),
                passed=report.passed,
                factual_score=report.final_scores.factual_accuracy,
                source_trace_score=report.final_scores.source_traceability,
                difficulty_match_score=report.final_scores.difficulty_match,
                coverage_score=report.final_scores.core_knowledge_coverage,
                decision=report.decision.value,
                evidence_refs_json=report.evidence_ref_ids,
                disagreement_summary_json={
                    "required": report.arbitration.required,
                    "disagreement_remains": report.arbitration.disagreement_remains,
                    "claim_set_hash": report.claim_set_hash,
                    "supported_claim_ids": report.supported_claim_ids,
                    "contradicted_claim_ids": report.contradicted_claim_ids,
                    "undetermined_claim_ids": report.undetermined_claim_ids,
                    "unresolved_claim_ids": report.unresolved_claim_ids,
                },
                review_rule_version="atomic-claims-20260814",
                issues_json=[item.model_dump(mode="json") for item in report.issues],
                suggestions_json=[item.suggested_revision for item in report.issues],
                target_knowledge_ids_json=report.target_knowledge_ids,
                covered_knowledge_ids_json=report.covered_knowledge_ids,
                missing_knowledge_ids_json=report.missing_knowledge_ids,
                verifiable_claim_count=report.quality_metrics.verifiable_claim_count,
                hallucinated_claim_count=report.quality_metrics.hallucinated_claim_count,
                hallucination_rate=report.quality_metrics.hallucination_rate,
                covered_core_knowledge_count=report.quality_metrics.covered_core_knowledge_count,
                target_core_knowledge_count=report.quality_metrics.target_core_knowledge_count,
                core_knowledge_coverage=report.quality_metrics.core_knowledge_coverage,
                quality_passed=report.quality_metrics.passed,
                revision_count=report.quality_metrics.revision_count,
                model_role_version="review-v4",
        )
        for key, value in values.items():
            setattr(stored_report, key, value)
    db.flush()
    if publish:
        _compose_published_package(db, task)
