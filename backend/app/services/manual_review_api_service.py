from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import conflict, not_found
from app.models import GenerationTask, ManualReviewTask
from app.repositories.manual_review_repo import ManualReviewRepository
from app.schemas.api_requests import ManualReviewDecisionRequest


def serialize_manual_review(item: ManualReviewTask, task: GenerationTask) -> dict[str, Any]:
    return {"manual_review_id": item.public_id, "task_id": task.public_id, "trigger_reason": item.trigger_reason, "status": item.status, "decision": item.decision, "review_comment": item.review_comment, "reviewed_by": item.reviewed_by, "created_at": item.created_at.isoformat() if item.created_at else None, "updated_at": item.updated_at.isoformat() if item.updated_at else None}


class ManualReviewApiService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = ManualReviewRepository(db)

    def list(self, status: str | None) -> list[dict[str, Any]]:
        return [serialize_manual_review(item, task) for item, task in self.repository.list(status)]

    def detail(self, review_id: str) -> dict[str, Any]:
        row = self.repository.detail(review_id)
        if row is None:
            raise not_found("MANUAL_REVIEW_NOT_FOUND", "人工复核任务不存在。")
        return serialize_manual_review(row[0], row[1])

    def decide(self, review_id: str, payload: ManualReviewDecisionRequest) -> tuple[dict[str, Any], str, str]:
        item = self.repository.get(review_id)
        if item is None:
            raise not_found("MANUAL_REVIEW_NOT_FOUND", "人工复核任务不存在。")
        if item.status != "pending":
            raise conflict("MANUAL_REVIEW_ALREADY_RESOLVED", "人工复核任务已经处理。")
        task = self.db.get(GenerationTask, item.task_id)
        if task is None or task.status != "waiting_human":
            raise conflict("TASK_NOT_WAITING_HUMAN_REVIEW", "生成任务当前不等待人工复核。")
        checkpoint = self.repository.checkpoint(task.public_id)
        if checkpoint is None or not (checkpoint.state_json or {}).get("native_checkpoint"):
            raise conflict("TASK_CHECKPOINT_NOT_RESUMABLE", "任务没有可恢复的检查点。")
        checkpoint.status = "resuming"
        item.status = "resolved"
        item.decision = payload.decision
        item.review_comment = payload.comment
        item.reviewed_by = payload.reviewed_by
        result = {**serialize_manual_review(item, task), "resume_thread_id": task.public_id, "resume_status": "scheduled"}
        return result, "manual_review", item.public_id
