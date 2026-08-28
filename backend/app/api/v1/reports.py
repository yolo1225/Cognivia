from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import Principal, assert_learner_access, get_current_user, require_task
from app.agents.contracts import EvidenceRef, EvidenceType, KnowledgeAssessment
from app.models import (
    AnswerRecord,
    DiagnosticQuestion,
    Feedback,
    GenerationTask,
    KnowledgeItem,
    Learner,
    LearningResource,
    ReviewReport,
)
from app.schemas.common import ApiResponse, ok
from app.services.profile_service import (
    is_initial_profile_ready,
    latest_path_for_profile,
    latest_profile_for_learner,
    profile_source,
    serialize_profile_detail,
)
from app.services.report_service import (
    build_learning_journey,
    build_learning_progress_comparison,
    refresh_learning_path,
)
from app.services.learning_path_service import normalize_path_for_domain, serialize_learning_path
from app.services.learning_adjustment_service import (
    pending_resource_proposals,
    recent_profile_changes,
)
from app.services.learning_package_service import current_package
from app.services.domain_runtime_service import DomainRuntimeError, load_domain_runtime
from app.services.profile_knowledge_state_service import (
    STATE_KEY,
    build_knowledge_state,
    public_knowledge_state,
)

router = APIRouter()

RESOURCE_TYPE_LABELS = {
    "lecture": "讲义",
    "practice_guide": "实训指导",
    "graded_quiz": "分级测验",
}


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None


def _resource_type_counts(resources: list[LearningResource]) -> dict[str, int]:
    counts = {resource_type: 0 for resource_type in RESOURCE_TYPE_LABELS}
    for resource in resources:
        counts[resource.resource_type] = counts.get(resource.resource_type, 0) + 1
    return counts


def _review_status_counts(resources: list[LearningResource]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for resource in resources:
        counts[resource.review_status] = counts.get(resource.review_status, 0) + 1
    return counts


def _source_coverage(resources: list[LearningResource]) -> int:
    source_ids: set[str] = set()
    for resource in resources:
        for source in resource.sources_json or []:
            if isinstance(source, dict):
                source_id = source.get("knowledge_id")
            else:
                source_id = str(source)
            if source_id:
                source_ids.add(str(source_id))
    return len(source_ids)


def _serialize_resource(resource: LearningResource, task: GenerationTask | None) -> dict[str, Any]:
    return {
        "resource_id": resource.public_id,
        "resource_type": resource.resource_type,
        "resource_type_label": RESOURCE_TYPE_LABELS.get(
            resource.resource_type, resource.resource_type
        ),
        "title": resource.title,
        "difficulty": resource.difficulty,
        "review_status": resource.review_status,
        "source_count": len(resource.sources_json or []),
        "generation_task_id": task.public_id if task else None,
        "generation_status": task.status if task else None,
        "generation_decision": task.decision if task else None,
        "generated_at": _iso(resource.created_at),
    }


def _legacy_knowledge_profile(db: Session, *, learner: Learner, domain_code: str) -> dict[str, Any]:
    """Build a read-only compatibility view without mutating historical profiles."""
    try:
        runtime = load_domain_runtime(db, domain_code)
    except DomainRuntimeError:
        return public_knowledge_state(None)
    if runtime.profile_config is None:
        return public_knowledge_state(None)
    rows = list(
        db.execute(
            select(AnswerRecord, DiagnosticQuestion, KnowledgeItem)
            .join(DiagnosticQuestion, DiagnosticQuestion.id == AnswerRecord.question_id)
            .join(KnowledgeItem, KnowledgeItem.id == AnswerRecord.knowledge_item_id)
            .where(
                AnswerRecord.learner_id == learner.id,
                AnswerRecord.scoring_status == "scored",
                KnowledgeItem.domain_code == domain_code,
            )
        )
    )
    evidence: list[EvidenceRef] = []
    assessments: list[KnowledgeAssessment] = []
    excluded: set[str] = set()
    for record, question, knowledge in rows:
        evidence_id = f"answer_record:{record.id}"
        confidence = float(record.confidence or 0.0)
        attempted = bool((record.answer_summary_json or {}).get("attempted", True))
        evidence.append(EvidenceRef(
            evidence_id=evidence_id,
            evidence_type=EvidenceType.SCORED_QUIZ,
            summary="历史正式评分记录兼容投影",
            knowledge_id=knowledge.public_id,
            confidence=confidence,
            confirmed=True,
        ))
        assessments.append(KnowledgeAssessment(
            assessment_id=f"legacy:{record.id}",
            evidence_id=evidence_id,
            knowledge_id=knowledge.public_id,
            score=float(record.score) if attempted else None,
            difficulty=question.difficulty,
            attempted=attempted,
            confidence=confidence,
        ))
        if record.scoring_uncertain:
            excluded.add(evidence_id)
    state = build_knowledge_state(
        config=runtime.profile_config,
        evidence=evidence,
        assessments=assessments,
        excluded_evidence_ids=excluded,
    )
    return public_knowledge_state(state, derived_legacy=True)


def _next_actions(
    *,
    has_profile: bool,
    resources: list[LearningResource],
    feedback_count: int,
    path_needs_refresh: bool,
) -> list[dict[str, str]]:
    if not has_profile:
        return [
            {
                "type": "diagnosis",
                "label": "完成诊断测评",
                "description": "先生成学习者画像，再进入资源生成与反馈闭环。",
                "route": "/diagnostic",
            }
        ]
    if not resources:
        return [
            {
                "type": "generation",
                "label": "生成个性化资源",
                "description": "基于当前画像生成讲义、实训指导和分级测验。",
                "route": "/dashboard?intent=generate",
            }
        ]
    if feedback_count == 0:
        return [
            {
                "type": "feedback",
                "label": "提交资源反馈",
                "description": "在学习资源页标记太难、太简单、看不懂或内容有误。",
                "route": "/resources",
            }
        ]
    if path_needs_refresh:
        return [
            {
                "type": "path_refresh",
                "label": "刷新学习路径",
                "description": "反馈已触发辅导动作，下一次打开画像或报告时应更新路径。",
                "route": "/report",
            }
        ]
    return [
        {
            "type": "continue_learning",
            "label": "继续下一轮学习",
            "description": "闭环已完成，可以进入下一轮资源学习或挑战任务。",
            "route": "/resources",
        }
    ]


@router.get("/learners/{learner_id}", response_model=ApiResponse)
def get_learning_report(
    learner_id: str,
    task_id: str | None = Query(None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    if task_id:
        task = require_task(db, principal, task_id)
        learner = db.get(Learner, task.learner_id)
    else:
        if principal.role == "admin" and principal.learner_id != learner_id:
            raise HTTPException(403, "管理员直访只能查看自己的学习报告")
        assert_learner_access(principal, learner_id)
        learner = db.scalar(select(Learner).where(Learner.public_id == learner_id))
    if learner is None:
        raise HTTPException(status_code=404, detail=f"Learner not found: {learner_id}")

    profile = latest_profile_for_learner(
        db, learner, task.domain_code if task_id and task is not None else learner.target_domain
    )
    path = latest_path_for_profile(db, profile) if profile is not None else None
    original_path_payload = dict(path.path_json or {}) if path is not None else None
    if path is not None:
        path.path_json = normalize_path_for_domain(
            db, domain_code=path.domain_code, payload=path.path_json or {}, previous_payload=path.path_json or {}
        )
    detail = serialize_profile_detail(db, learner, profile, path=path)
    path_refresh_performed = False
    if path is not None and path.needs_refresh and profile is not None:
        refresh_learning_path(
            db=db,
            path=path,
            profile=profile,
            profile_detail=detail,
        )
        detail["learning_path"] = serialize_learning_path(path)
        db.commit()
        path_refresh_performed = True
    elif path is not None:
        if path.path_json != original_path_payload:
            db.commit()
    learning_path = detail.get("learning_path") or {}
    if path is not None and isinstance(learning_path, dict):
        node_tasks = list(
            db.scalars(
                select(GenerationTask)
                .where(GenerationTask.learning_path_id == path.id)
                .order_by(GenerationTask.id.desc())
            )
        )
        latest_by_node = {}
        for node_task in node_tasks:
            if node_task.path_node_id:
                latest_by_node.setdefault(node_task.path_node_id, node_task)
        for node in learning_path.get("nodes") or []:
            node_task = latest_by_node.get(node.get("path_node_id"))
            status = node_task.status if node_task else None
            node["resource_state"] = (
                "ready" if status == "completed"
                else "failed" if status == "failed"
                else "generating" if status in {"pending", "retry_pending", "running"}
                else "not_generated"
            )
            node["resource_task_id"] = node_task.public_id if node_task else None
    stages = learning_path.get("stages", []) if isinstance(learning_path, dict) else []
    path_needs_refresh = bool(path.needs_refresh) if path else False

    active_domain_code = profile.domain_code if profile else learner.target_domain
    resource_rows = list(
        db.execute(
            select(LearningResource, GenerationTask)
            .join(GenerationTask, GenerationTask.id == LearningResource.generation_task_id)
            .where(
                GenerationTask.learner_id == learner.id,
                GenerationTask.domain_code == active_domain_code,
                LearningResource.is_current.is_(True),
                LearningResource.review_status == "passed",
            )
            .order_by(LearningResource.id.desc())
        )
    )
    resources = [resource for resource, _task in resource_rows]
    recent_resources = [_serialize_resource(resource, task) for resource, task in resource_rows[:6]]

    review_reports = list(
        db.scalars(
            select(ReviewReport)
            .join(LearningResource, LearningResource.id == ReviewReport.resource_id)
            .join(GenerationTask, GenerationTask.id == LearningResource.generation_task_id)
            .where(GenerationTask.learner_id == learner.id, GenerationTask.domain_code == active_domain_code)
            .order_by(ReviewReport.id.desc())
        )
    )
    feedback_rows = list(
        db.execute(
            select(Feedback, LearningResource)
            .join(LearningResource, LearningResource.id == Feedback.resource_id)
            .join(GenerationTask, GenerationTask.id == LearningResource.generation_task_id)
            .where(Feedback.learner_id == learner.id)
            .where(GenerationTask.domain_code == active_domain_code)
            .order_by(Feedback.id.desc())
        )
    )
    recent_feedback = [
        {
            "resource_id": resource.public_id,
            "resource_title": resource.title,
            "feedback_type": feedback.feedback_type,
            "rating": feedback.rating,
            "triggered_action": feedback.triggered_action,
            "created_at": _iso(feedback.created_at),
        }
        for feedback, resource in feedback_rows[:5]
    ]
    diagnostic_summary = detail.get("diagnostic_summary", {})
    has_diagnosis = int(diagnostic_summary.get("answer_count") or 0) > 0
    has_profile = is_initial_profile_ready(profile)
    passed_reviews = sum(1 for report in review_reports if report.passed)
    reviewed_resource_count = len(review_reports)
    feedback_count = len(feedback_rows)
    adjustment_proposals = pending_resource_proposals(
        db,
        learner_id=learner.id,
        domain_code=profile.domain_code if profile else learner.target_domain,
    )
    profile_changes = recent_profile_changes(
        db,
        learner_id=learner.id,
        domain_code=profile.domain_code if profile else learner.target_domain,
    )
    internal_ability = dict(profile.ability_profile_json or {}) if profile else {}
    knowledge_profile = (
        public_knowledge_state(internal_ability.get(STATE_KEY))
        if internal_ability.get(STATE_KEY)
        else _legacy_knowledge_profile(db, learner=learner, domain_code=active_domain_code)
    )
    public_ability = {
        key: value
        for key, value in internal_ability.items()
        if key not in {STATE_KEY}
    }
    package_task = current_package(
        db,
        learner_id=learner.id,
        domain_code=active_domain_code,
    )
    node_gate = None
    if path is not None and profile is not None:
        from app.services.node_mastery_service import build_node_gate

        node_gate = build_node_gate(
            db,
            path=path,
            profile=profile,
            package_task=package_task,
        )


    return ok(
        {
            "learner_id": learner.public_id,
            "domain_code": active_domain_code,
            "profile_id": detail.get("profile_id"),
            "profile_type": detail.get("profile_type"),
            "profile_source": profile_source(profile) if profile else None,
            "profile_ready": has_profile,
            "diagnosis_completed": is_initial_profile_ready(profile),
            "education_level": detail.get("education_level", ""),
            "major": detail.get("major", ""),
            "direction_tags": detail.get("direction_tags", []),
            "context_snapshot": detail.get("context_snapshot", {}),
            "radar": detail.get("radar", [0, 0, 0, 0, 0]),
            "ability_profile": public_ability,
            "path": [stage.get("name", "") for stage in stages],
            "path_detail": stages,
            "learning_path": learning_path,
            "node_gate": node_gate,
            "weak_knowledge": detail.get("weak_knowledge", []),
            "knowledge_states": knowledge_profile["knowledge_states"],
            "knowledge_status_counts": knowledge_profile["status_counts"],
            "assessment_coverage": knowledge_profile["coverage"],
            "knowledge_state_derived_legacy": knowledge_profile["derived_legacy"],
            "dimension_status": dict(internal_ability.get("dimension_status") or {}),
            "profile_confidence": profile.confidence if profile else 0.0,
            "diagnostic_summary": diagnostic_summary,
            "loop_status": {
                "diagnosis": "completed" if has_diagnosis else "pending",
                "profile": "completed" if has_profile else "pending",
                "generation": "completed" if resources else "pending",
                "review": "completed" if reviewed_resource_count else "pending",
                "feedback": "completed" if feedback_count else "pending",
                "path_update": (
                    "refreshed"
                    if path_refresh_performed
                    else "needs_refresh"
                    if path_needs_refresh
                    else "current"
                ),
            },
            "resource_summary": {
                "total": len(resources),
                "by_type": _resource_type_counts(resources),
                "recent": recent_resources,
            },
            "review_summary": {
                "total_reports": reviewed_resource_count,
                "passed": passed_reviews,
                "review_status_counts": _review_status_counts(resources),
                "source_coverage": _source_coverage(resources),
            },
            "feedback_summary": {
                "total": feedback_count,
                "latest_action": recent_feedback[0]["triggered_action"]
                if recent_feedback
                else None,
                "learning_path_needs_refresh": path_needs_refresh,
                "path_refresh_performed": path_refresh_performed,
                "recent": recent_feedback,
            },
            "learning_adjustments": adjustment_proposals,
            "profile_changes": profile_changes,
            "progress_comparison": build_learning_progress_comparison(
                db, learner=learner, current_profile=profile, path=path
            ),
            "next_actions": _next_actions(
                has_profile=has_profile,
                resources=resources,
                feedback_count=feedback_count,
                path_needs_refresh=path_needs_refresh,
            ),
        }
    )


@router.get("/learners/{learner_id}/learning-journey", response_model=ApiResponse)
def get_learning_journey(
    learner_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    if principal.role == "admin" and principal.learner_id != learner_id:
        raise HTTPException(403, "管理员直访只能查看自己的学习历程")
    assert_learner_access(principal, learner_id)
    learner = db.scalar(select(Learner).where(Learner.public_id == learner_id))
    if learner is None:
        raise HTTPException(status_code=404, detail=f"Learner not found: {learner_id}")
    return ok(
        build_learning_journey(
            db,
            learner=learner,
            domain_code=learner.target_domain,
        )
    )
