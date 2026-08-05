from app.agents.contracts import ReviewReport as V2ReviewReport
from app.agents.v2_nodes import V2_GRAPH_STATE
from app.models import GenerationTask, LearnerProfile, LearningResource, ReviewReport


def _review_status(report: V2ReviewReport) -> str:
    if report.passed:
        return "passed"
    if report.decision.value == "rejected":
        return "failed"
    return "revision_required"


def persist_generated_resources(
    db,
    task: GenerationTask,
    profile: LearnerProfile,
    state: V2_GRAPH_STATE,
) -> None:
    profile_payload = profile.ability_profile_json or {}
    existing_count = (
        db.query(LearningResource)
        .filter(LearningResource.generation_task_id == task.id)
        .count()
    )
    if existing_count:
        return

    source_resource = db.get(LearningResource, task.source_resource_id) if task.source_resource_id else None
    generation = state.get("generate_resource")
    review = state.get("review_resource")
    finalization = state.get("finalize_task")
    if generation is None or review is None or finalization is None:
        return
    reports = {item.resource_type: item for item in review.reports}
    human_approved = bool(
        state.get("human_review") and state["human_review"].decision.value == "approve"
    )
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
        resource = LearningResource(
            public_id=f"res_{task.public_id}_{draft.resource_type.value}_v{version}",
            generation_task_id=task.id,
            resource_type=draft.resource_type.value,
            title=draft.structured_content.title,
            content_md=draft.content_md,
            difficulty=draft.difficulty,
            learner_profile_type=profile_payload.get("profile_type", ""),
            sources_json=[source.model_dump(mode="json") for source in draft.source_refs],
            version=version,
            review_status="passed" if human_approved else _review_status(report),
            series_id=series_id,
            previous_resource_id=previous.id if previous else None,
            is_current=True,
            adaptation_reason=finalization.decision_reason,
        )
        db.add(resource)
        db.flush()
        if not resource.series_id:
            resource.series_id = resource.public_id
        if previous:
            previous.is_current = False

        db.add(
            ReviewReport(
                resource_id=resource.id,
                task_id=task.id,
                primary_review_json=report.primary_review.model_dump(mode="json"),
                secondary_review_json=report.secondary_review.model_dump(mode="json"),
                arbitration_json=report.arbitration.model_dump(mode="json"),
                manual_review_required=report.manual_review_required,
                passed=human_approved or report.passed,
                factual_score=report.final_scores.factual_accuracy,
                source_trace_score=report.final_scores.source_traceability,
                difficulty_match_score=report.final_scores.difficulty_match,
                coverage_score=report.final_scores.core_knowledge_coverage,
                decision="passed" if human_approved else report.decision.value,
                evidence_refs_json=report.evidence_ref_ids,
                disagreement_summary_json={
                    "required": report.arbitration.required,
                    "disagreement_remains": report.arbitration.disagreement_remains,
                },
                review_rule_version="review-v2",
                issues_json=[item.model_dump(mode="json") for item in report.issues],
                suggestions_json=[item.suggested_revision for item in report.issues],
            )
        )
