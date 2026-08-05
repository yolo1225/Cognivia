from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import conflict, not_found, validation_error
from app.repositories.resource_repo import ResourceRepository
from app.schemas.api_requests import ResourceExportRequest, ResourceFeedbackRequest
from app.services.demo_flow_service import serialize_resource
from app.services.feedback_service import record_quick_feedback, serialize_feedback_decision
from app.services.learner_service import get_or_create_demo_learner
from app.services.profile_service import default_profile_for_learner
from app.services.resource_export_service import export_resource


class ResourceApiService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = ResourceRepository(db)

    def list(self, include_unpublished: bool) -> list[dict[str, Any]]:
        return [serialize_resource(resource, task) for resource, task in self.repository.list(include_unpublished)]

    def submit_feedback(
        self, resource_id: str, payload: ResourceFeedbackRequest
    ) -> tuple[dict[str, Any], str, str | None]:
        resource = self.repository.get(resource_id)
        if resource is None:
            raise not_found("RESOURCE_NOT_FOUND", f"资源不存在：{resource_id}")
        learner = get_or_create_demo_learner(self.db, payload.learner_id)
        profile = default_profile_for_learner(self.db, learner)
        feedback, task = record_quick_feedback(
            self.db,
            learner=learner,
            profile=profile,
            resource=resource,
            feedback_type=payload.feedback_type,
            rating=payload.rating,
            comment=(payload.selected_text or payload.comment or ""),
        )
        result = serialize_feedback_decision(feedback, task)
        result["resource_id"] = resource.public_id
        return result, "resource_feedback", task.public_id if task else None

    def versions(self, resource_id: str) -> list[dict[str, Any]]:
        resource = self.repository.get(resource_id)
        if resource is None:
            raise not_found("RESOURCE_NOT_FOUND", f"资源不存在：{resource_id}")
        series_id = resource.series_id or resource.public_id
        return [{"resource_id": item.public_id, "series_id": series_id, "version": item.version, "is_current": item.is_current, "review_status": item.review_status, "adaptation_reason": item.adaptation_reason, "created_at": item.created_at.isoformat() if item.created_at else None} for item in self.repository.versions(series_id)]

    def export(self, resource_id: str, payload: ResourceExportRequest) -> dict[str, Any]:
        resource = self.repository.get(resource_id)
        if resource is None:
            raise not_found("RESOURCE_NOT_FOUND", f"资源不存在：{resource_id}")
        if resource.review_status != "passed":
            raise conflict("RESOURCE_NOT_APPROVED", "未通过审核的资源不能导出。")
        try:
            return export_resource(self.db, resource, payload.format, payload.audience)
        except ValueError as exc:
            raise validation_error("RESOURCE_EXPORT_INVALID", str(exc)) from exc
