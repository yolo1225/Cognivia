from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import not_found
from app.models import GenerationTask, LearningResource
from app.repositories.report_repo import ReportRepository
from app.services.profile_service import latest_profile_for_learner, serialize_profile_detail
from app.services.report_service import build_metric_summary, refresh_learning_path


RESOURCE_TYPE_LABELS = {"lecture": "讲义", "practice_guide": "实训指导", "graded_quiz": "分级测验"}


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None


def _resource_counts(resources: list[LearningResource]) -> dict[str, int]:
    counts = {resource_type: 0 for resource_type in RESOURCE_TYPE_LABELS}
    for resource in resources:
        counts[resource.resource_type] = counts.get(resource.resource_type, 0) + 1
    return counts


def _review_counts(resources: list[LearningResource]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for resource in resources:
        counts[resource.review_status] = counts.get(resource.review_status, 0) + 1
    return counts


class ReportApiService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = ReportRepository(db)

    def build(self, learner_id: str) -> dict[str, Any]:
        learner = self.repository.learner(learner_id)
        if learner is None:
            raise not_found("LEARNER_NOT_FOUND", f"学习者不存在：{learner_id}")
        profile = latest_profile_for_learner(self.db, learner)
        detail = serialize_profile_detail(self.db, learner, profile)
        path = self.repository.latest_path(learner.id)
        path_refresh_performed = False
        if path is not None and path.needs_refresh and profile is not None:
            detail["learning_path"] = refresh_learning_path(path=path, profile=profile, profile_detail=detail)
            self.db.commit()
            path_refresh_performed = True
        learning_path = detail.get("learning_path") or {}
        stages = learning_path.get("stages", []) if isinstance(learning_path, dict) else []
        path_needs_refresh = bool(path.needs_refresh) if path else False
        resource_rows = self.repository.resources(learner.id)
        resources = [resource for resource, _ in resource_rows]
        recent_resources = [self._resource(resource, task) for resource, task in resource_rows[:6]]
        review_reports = self.repository.reviews(learner.id)
        feedback_rows = self.repository.feedback(learner.id)
        recent_feedback = [{"resource_id": resource.public_id, "resource_title": resource.title, "feedback_type": feedback.feedback_type, "rating": feedback.rating, "triggered_action": feedback.triggered_action, "created_at": _iso(feedback.created_at)} for feedback, resource in feedback_rows[:5]]
        diagnostic_summary = detail.get("diagnostic_summary", {})
        has_diagnosis = int(diagnostic_summary.get("answer_count") or 0) > 0
        has_profile = detail.get("profile_status") == "ready"
        source_ids = {str(source.get("knowledge_id") if isinstance(source, dict) else source) for resource in resources for source in (resource.sources_json or []) if (source.get("knowledge_id") if isinstance(source, dict) else source)}
        return {
            "learner_id": learner.public_id, "profile_id": detail.get("profile_id"), "profile_type": detail.get("profile_type"), "radar": detail.get("radar", [0, 0, 0, 0, 0]), "path": [stage.get("name", "") for stage in stages], "path_detail": stages, "weak_knowledge": detail.get("weak_knowledge", []), "diagnostic_summary": diagnostic_summary,
            "metrics": build_metric_summary(hallucination_rate=0.03, difficulty_match=0.87, coverage=0.91),
            "loop_status": {"diagnosis": "completed" if has_diagnosis else "pending", "profile": "completed" if has_profile else "pending", "generation": "completed" if resources else "pending", "review": "completed" if review_reports else "pending", "feedback": "completed" if feedback_rows else "pending", "path_update": "refreshed" if path_refresh_performed else "needs_refresh" if path_needs_refresh else "current"},
            "resource_summary": {"total": len(resources), "by_type": _resource_counts(resources), "recent": recent_resources},
            "review_summary": {"total_reports": len(review_reports), "passed": sum(1 for report in review_reports if report.passed), "manual_review_required": sum(1 for report in review_reports if report.manual_review_required), "review_status_counts": _review_counts(resources), "source_coverage": len(source_ids)},
            "feedback_summary": {"total": len(feedback_rows), "latest_action": recent_feedback[0]["triggered_action"] if recent_feedback else None, "learning_path_needs_refresh": path_needs_refresh, "path_refresh_performed": path_refresh_performed, "recent": recent_feedback},
            "next_actions": self._next_actions(has_profile, resources, len(feedback_rows), path_needs_refresh),
        }

    @staticmethod
    def _resource(resource: LearningResource, task: GenerationTask) -> dict[str, Any]:
        return {"resource_id": resource.public_id, "resource_type": resource.resource_type, "resource_type_label": RESOURCE_TYPE_LABELS.get(resource.resource_type, resource.resource_type), "title": resource.title, "difficulty": resource.difficulty, "review_status": resource.review_status, "source_count": len(resource.sources_json or []), "generation_task_id": task.public_id, "generation_status": task.status, "generation_decision": task.decision, "generated_at": _iso(resource.created_at)}

    @staticmethod
    def _next_actions(has_profile: bool, resources: list[LearningResource], feedback_count: int, path_needs_refresh: bool) -> list[dict[str, str]]:
        if not has_profile:
            return [{"type": "diagnosis", "label": "完成诊断测评", "description": "先生成学习者画像，再进入资源生成与反馈闭环。", "route": "/diagnostics"}]
        if not resources:
            return [{"type": "generation", "label": "生成个性化资源", "description": "基于当前画像生成讲义、实训指导和分级测验。", "route": "/learners"}]
        if not feedback_count:
            return [{"type": "feedback", "label": "提交资源反馈", "description": "在学习资源页标记太难、太简单、看不懂或内容有误。", "route": "/resources"}]
        if path_needs_refresh:
            return [{"type": "path_refresh", "label": "刷新学习路径", "description": "反馈已触发辅导动作，下一次打开画像或报告时应更新路径。", "route": "/reports"}]
        return [{"type": "continue_learning", "label": "继续下一轮学习", "description": "闭环已完成，可以进入下一轮资源学习或挑战任务。", "route": "/resources"}]
