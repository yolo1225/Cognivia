from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import conflict, not_found
from app.models import Learner
from app.repositories.tutoring_repo import TutoringRepository
from app.schemas.api_requests import TutoringMessageRequest, TutoringSessionCreateRequest
from app.services.learner_service import get_or_create_demo_learner
from app.services.profile_service import default_profile_for_learner
from app.services.tutoring_service import add_learner_message, create_session, serialize_session


class TutoringApiService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = TutoringRepository(db)

    def create_session(self, payload: TutoringSessionCreateRequest) -> tuple[dict[str, Any], str, str]:
        learner = get_or_create_demo_learner(self.db, payload.learner_id)
        resource = self.repository.resource(payload.resource_id)
        if resource is None:
            raise not_found("RESOURCE_NOT_FOUND", "导学需要已发布的学习资源。")
        if resource.review_status != "passed" or not resource.is_current:
            raise conflict("RESOURCE_NOT_TUTORABLE", "仅当前且审核通过的资源可以进入导学。")
        session = create_session(self.db, learner=learner, resource=resource)
        return serialize_session(self.db, session), "tutoring_session", session.public_id

    def add_message(self, session_id: str, payload: TutoringMessageRequest) -> tuple[dict[str, Any], str, str | None]:
        session = self.repository.session(session_id)
        if session is None:
            raise not_found("TUTORING_SESSION_NOT_FOUND", "导学会话不存在。")
        learner = self.db.get(Learner, session.learner_id)
        if learner is None:
            raise not_found("LEARNER_NOT_FOUND", "学习者不存在。")
        profile = default_profile_for_learner(self.db, learner)
        try:
            _, reply, feedback, task, output = add_learner_message(self.db, session=session, profile=profile, content=payload.content.strip(), evidence=payload.evidence)
        except ValueError as exc:
            raise conflict("TUTORING_SESSION_INVALID", str(exc)) from exc
        result = {
            "session_id": session.public_id,
            "reply": {"message_id": reply.public_id, "message_type": reply.message_type, "content": reply.content},
            "feedback_intent": output["feedback_intent"],
            "recommended_action": feedback.recommended_action,
            "profile_update_required": feedback.feedback_intent in {"too_hard", "too_easy"} and any(
                item.get("type") in {"scored_quiz", "diagnostic_result", "validated_behavior"} and (float(item.get("confidence", 0) or 0) >= 0.7 or item.get("confirmed") is True)
                for item in (feedback.profile_change_evidence_json or []) if isinstance(item, dict)
            ),
            "decision_reason": feedback.decision_reason,
            "task_id": task.public_id if task else None,
        }
        return result, "tutoring_message", reply.public_id

    def session_detail(self, session_id: str) -> dict[str, Any]:
        session = self.repository.session(session_id)
        if session is None:
            raise not_found("TUTORING_SESSION_NOT_FOUND", "导学会话不存在。")
        return serialize_session(self.db, session)
