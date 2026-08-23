from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.contracts import AnalyzeProfileOutput
from app.models import (
    AnswerRecord,
    Feedback,
    GenerationTask,
    LearnerProfile,
    LearningPath,
    LearningResource,
)
from app.services.contract_mapping import ability_profile_payload
from app.services.learning_path_service import normalize_path_for_domain
from app.services.profile_service import build_learning_path_from_snapshot, public_id


def persist_profile_revision(
    db: Session,
    *,
    original: LearnerProfile,
    analysis: AnalyzeProfileOutput,
    trigger_feedback_id: int | None,
) -> tuple[LearnerProfile, LearningPath | None]:
    if not analysis.profile_update_required:
        return original, None
    snapshot = analysis.profile
    if (
        snapshot.profile_id == original.public_id
        and snapshot.profile_version <= original.profile_version
    ):
        return original, None

    ability_payload = {
        **dict(original.ability_profile_json or {}),
        **ability_profile_payload(snapshot),
    }
    next_profile = LearnerProfile(
        public_id=public_id("profile"),
        learner_id=original.learner_id,
        domain_code=original.domain_code,
        ability_profile_json=ability_payload,
        weak_knowledge_json=[
            item.model_dump(mode="json") for item in snapshot.weak_knowledge
        ],
        profile_version=snapshot.profile_version,
        previous_profile_id=original.id,
        profile_source="feedback_revision",
        diagnosis_completed=True,
        changed_dimensions_json=analysis.changed_dimensions,
        evidence_refs_json=[
            item.model_dump(mode="json") for item in analysis.evidence_refs
        ],
        confidence=analysis.confidence,
        context_snapshot_json=original.context_snapshot_json or {},
        trigger_feedback_id=trigger_feedback_id,
        decision_reason=analysis.decision_reason,
        profile_changed_at=datetime.now(UTC),
    )
    db.add(next_profile)
    db.flush()

    consumed_ids = {item.evidence_id for item in analysis.evidence_refs}
    for record in db.scalars(
        select(AnswerRecord).where(AnswerRecord.learner_id == original.learner_id)
    ):
        if f"answer_record:{record.id}" in consumed_ids:
            summary = dict(record.answer_summary_json or {})
            summary["consumed_by_profile_id"] = next_profile.id
            record.answer_summary_json = summary

    feedback = db.get(Feedback, trigger_feedback_id) if trigger_feedback_id else None
    if feedback is not None:
        affected_knowledge_ids = list(
            dict.fromkeys(
                [
                    *analysis.affected_scope.knowledge_ids,
                    *[
                        item.knowledge_id
                        for item in analysis.evidence_refs
                        if item.knowledge_id
                    ],
                ]
            )
        )
        learner_resources = db.scalars(
            select(LearningResource)
            .join(GenerationTask, GenerationTask.id == LearningResource.generation_task_id)
            .where(
                GenerationTask.learner_id == original.learner_id,
                LearningResource.is_current.is_(True),
            )
        )
        feedback.profile_update_required = True
        feedback.decision_reason = analysis.decision_reason
        feedback.decision_confidence = analysis.confidence
        feedback.affected_knowledge_ids_json = affected_knowledge_ids
        feedback.affected_path_node_ids_json = list(
            analysis.affected_scope.path_node_ids
        )
        feedback.affected_resource_ids_json = [
            resource.public_id
            for resource in learner_resources
            if any(
                source.get("knowledge_id") in affected_knowledge_ids
                for source in (resource.sources_json or [])
                if isinstance(source, dict)
            )
        ]

    previous_paths = list(
        db.scalars(
            select(LearningPath)
            .where(LearningPath.profile_id == original.id)
            .order_by(LearningPath.created_at.desc(), LearningPath.id.desc())
        )
    )
    previous_path = previous_paths[0] if previous_paths else None
    for path in previous_paths:
        path.needs_refresh = True
        if path.status == "active":
            path.status = "superseded"
    path_payload = build_learning_path_from_snapshot(
        next_profile.ability_profile_json,
        next_profile.weak_knowledge_json,
    )
    path_payload = normalize_path_for_domain(
        db,
        domain_code=original.domain_code,
        payload=path_payload,
        previous_payload=previous_path.path_json if previous_path else None,
    )
    next_path = LearningPath(
        public_id=public_id("path"),
        learner_id=original.learner_id,
        profile_id=next_profile.id,
        domain_code=original.domain_code,
        status="active",
        path_json=path_payload,
        needs_refresh=False,
    )
    db.add(next_path)
    db.flush()
    return next_profile, next_path
