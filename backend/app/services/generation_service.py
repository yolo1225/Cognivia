from app.agents.contracts import ReviewReport as ContractReviewReport
from app.agents.nodes import GRAPH_STATE
from app.models import GenerationTask, LearnerProfile, LearningResource, ReviewReport


def _review_status(report: ContractReviewReport) -> str:
    if report.passed:
        return "passed"
    if report.decision.value == "rejected":
        return "failed"
    return "revision_required"


def persist_generated_resources(
    db,
    task: GenerationTask,
    profile: LearnerProfile,
    state: GRAPH_STATE,
) -> None:
    profile_payload = profile.ability_profile_json or {}
    source_resource = db.get(LearningResource, task.source_resource_id) if task.source_resource_id else None
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
    publish = (
        finalization.decision.value == "completed"
        and len(review.reports) == 3
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
        previous = (
            source_resource
            if source_resource is not None and source_resource.resource_type == draft.resource_type.value
            else None
        )
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
