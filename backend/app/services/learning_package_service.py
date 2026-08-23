from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    GenerationTask,
    KnowledgeUpdateImpact,
    Learner,
    LearnerProfile,
    LearningPath,
    LearningPackageResource,
    LearningResource,
    ReviewReport,
)
from app.rag.readiness import candidate_rag_status
from app.services.demo_flow_service import serialize_resource
from app.services.node_generation_target_service import generation_basis_for_task


RESOURCE_ORDER = {"lecture": 0, "practice_guide": 1, "graded_quiz": 2}


def ensure_package_members(db: Session, task: GenerationTask) -> list[LearningPackageResource]:
    members = list(
        db.scalars(
            select(LearningPackageResource)
            .where(LearningPackageResource.package_task_id == task.id)
            .order_by(LearningPackageResource.sort_order, LearningPackageResource.id)
        )
    )
    if members:
        return members
    resources = list(
        db.scalars(
            select(LearningResource)
            .where(LearningResource.generation_task_id == task.id)
            .order_by(LearningResource.id)
        )
    )
    for resource in resources:
        member = LearningPackageResource(
            package_task_id=task.id,
            resource_id=resource.id,
            membership_type="generated",
            freshness_status=(
                "knowledge_changed" if resource.review_status == "review_stale" else "current"
            ),
            sort_order=RESOURCE_ORDER.get(resource.resource_type, 99),
        )
        db.add(member)
        members.append(member)
    if members:
        db.flush()
    return sorted(members, key=lambda item: (item.sort_order, item.id or 0))


def package_member_rows(
    db: Session, task: GenerationTask
) -> list[tuple[LearningPackageResource, LearningResource]]:
    ensure_package_members(db, task)
    return list(
        db.execute(
            select(LearningPackageResource, LearningResource)
            .join(LearningResource, LearningResource.id == LearningPackageResource.resource_id)
            .where(LearningPackageResource.package_task_id == task.id)
            .order_by(LearningPackageResource.sort_order, LearningPackageResource.id)
        )
    )


def current_package(db: Session, *, learner_id: int, domain_code: str) -> GenerationTask | None:
    path = db.scalar(
        select(LearningPath)
        .where(
            LearningPath.learner_id == learner_id,
            LearningPath.domain_code == domain_code,
            LearningPath.status.in_(["active", "completed"]),
        )
        .order_by(LearningPath.created_at.desc(), LearningPath.id.desc())
    )
    current_node_id = (path.path_json or {}).get("current_node_id") if path else None
    if path is not None and current_node_id is None:
        return None
    task = db.scalar(
        select(GenerationTask)
        .where(
            GenerationTask.learner_id == learner_id,
            GenerationTask.domain_code == domain_code,
            GenerationTask.is_current_package.is_(True),
            GenerationTask.learning_path_id == path.id if path is not None else True,
            GenerationTask.path_node_id == current_node_id if path is not None else True,
        )
        .order_by(GenerationTask.id.desc())
    )
    if task is not None:
        return task
    if path is not None:
        return None
    # Compatibility for databases created before package membership existed.
    return db.scalar(
        select(GenerationTask)
        .join(LearningResource, LearningResource.generation_task_id == GenerationTask.id)
        .where(
            GenerationTask.learner_id == learner_id,
            GenerationTask.domain_code == domain_code,
            GenerationTask.status == "completed",
        )
        .order_by(GenerationTask.created_at.desc(), GenerationTask.id.desc())
    )


def latest_impact(db: Session, task: GenerationTask) -> KnowledgeUpdateImpact | None:
    return db.scalar(
        select(KnowledgeUpdateImpact)
        .where(KnowledgeUpdateImpact.package_task_id == task.id)
        .order_by(KnowledgeUpdateImpact.id.desc())
    )


def serialize_package(
    db: Session, task: GenerationTask, *, include_resolved_impact: bool = False
) -> dict:
    learner = db.get(Learner, task.learner_id)
    profile = db.get(LearnerProfile, task.profile_id)
    path = db.get(LearningPath, task.learning_path_id) if task.learning_path_id else None
    node = ((path.path_json or {}).get("node_states") or {}).get(task.path_node_id) if path else None
    rows = package_member_rows(db, task)
    report_by_resource: dict[int, ReviewReport] = {}
    if rows:
        resource_ids = [resource.id for _, resource in rows]
        reports = list(
            db.scalars(
                select(ReviewReport)
                .where(ReviewReport.resource_id.in_(resource_ids))
                .order_by(ReviewReport.id.desc())
            )
        )
        for report in reports:
            report_by_resource.setdefault(report.resource_id, report)
    resources = []
    for member, resource in rows:
        payload = serialize_resource(resource, db.get(GenerationTask, resource.generation_task_id))
        payload.update(
            {
                "membership_type": member.membership_type,
                "freshness_status": member.freshness_status,
                "quality_metrics": _quality_metrics(report_by_resource.get(resource.id)),
            }
        )
        resources.append(payload)
    impact = latest_impact(db, task)
    rag = candidate_rag_status(task.domain_code)
    impact_payload = None
    visible_impact_statuses = {"pending", "dismissed", "refreshing"}
    if include_resolved_impact:
        visible_impact_statuses.add("resolved")
    if impact is not None and impact.status in visible_impact_statuses:
        impact_payload = {
            "impact_id": impact.public_id,
            "status": impact.status,
            "reason": impact.reason,
            "affected_knowledge_ids": impact.affected_knowledge_ids_json or [],
            "affected_resource_ids": impact.affected_resource_ids_json or [],
            "affected_resource_count": len(impact.affected_resource_ids_json or []),
            "change_sequence": impact.change_sequence,
            "refresh_available": (
                bool(rag.get("ready")) and impact.status in {"pending", "dismissed"}
            ),
            "index_status": "ready" if rag.get("ready") else "updating",
        }
    return {
        "package_id": task.public_id,
        "task_id": task.public_id,
        "learner_id": learner.public_id if learner else None,
        "profile_id": profile.public_id if profile else None,
        "profile_version": profile.profile_version if profile else None,
        "status": task.status,
        "path_id": path.public_id if path else None,
        "path_node_id": task.path_node_id,
        "path_node_title": node.get("title") if isinstance(node, dict) else None,
        "path_node_order": node.get("path_order") if isinstance(node, dict) else None,
        "generation_basis": generation_basis_for_task(db, task),
        "event_type": task.event_type,
        "source_task_id": (
            db.get(GenerationTask, task.source_task_id).public_id if task.source_task_id else None
        ),
        "is_current_package": task.is_current_package,
        "resources": resources,
        "knowledge_impact": impact_payload,
        "package_quality": task.package_quality_json or None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }


def _quality_metrics(report: ReviewReport | None) -> dict | None:
    if report is None:
        return None
    return {
        "quality_rule_version": report.quality_rule_version,
        "evaluated_claim_count": report.evaluated_claim_count,
        "contradicted_claim_count": report.contradicted_claim_count,
        "evidence_insufficient_claim_count": report.evidence_insufficient_claim_count,
        "unresolved_claim_count": report.unresolved_claim_count,
        "verifiable_claim_count": report.verifiable_claim_count,
        "hallucinated_claim_count": report.hallucinated_claim_count,
        "hallucination_rate": report.hallucination_rate,
        "difficulty_match_score": report.difficulty_match_score,
        "covered_core_knowledge_count": report.covered_core_knowledge_count,
        "target_core_knowledge_count": report.target_core_knowledge_count,
        "core_knowledge_coverage": report.core_knowledge_coverage,
        "passed": report.quality_passed,
        "revision_count": report.revision_count,
    }


def record_package_impact(
    db: Session,
    *,
    task: GenerationTask,
    affected_knowledge_ids: set[str],
    affected_resources: list[LearningResource],
    reason: str,
) -> KnowledgeUpdateImpact:
    impact = latest_impact(db, task)
    resource_ids = {resource.public_id for resource in affected_resources}
    knowledge_ids = set(affected_knowledge_ids)
    if impact is None or impact.status in {"resolved", "cancelled"}:
        impact = KnowledgeUpdateImpact(
            public_id=f"impact_{uuid4().hex[:12]}",
            package_task_id=task.id,
            affected_knowledge_ids_json=sorted(knowledge_ids),
            affected_resource_ids_json=sorted(resource_ids),
            status="pending",
            reason=reason,
        )
        db.add(impact)
    else:
        impact.affected_knowledge_ids_json = sorted(
            set(impact.affected_knowledge_ids_json or []) | knowledge_ids
        )
        impact.affected_resource_ids_json = sorted(
            set(impact.affected_resource_ids_json or []) | resource_ids
        )
        impact.status = "pending"
        impact.reason = reason
        impact.change_sequence += 1
        impact.dismissed_at = None
    return impact


def dismiss_impact(db: Session, impact: KnowledgeUpdateImpact) -> None:
    impact.status = "dismissed"
    impact.dismissed_at = datetime.now(UTC)
