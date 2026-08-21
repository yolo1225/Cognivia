from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import conflict, not_found
from app.models import Learner
from app.repositories.learner_repo import LearnerRepository
from app.schemas.api_requests import LearnerCreateRequest
from app.services.learner_service import get_or_create_demo_learner
from app.services.profile_service import (
    latest_profile_for_learner,
    profile_ability_level,
    serialize_profile_detail,
)


def serialize_learner_summary(db: Session, learner: Learner) -> dict[str, Any]:
    profile = latest_profile_for_learner(db, learner)
    ability_profile = profile.ability_profile_json if profile else {}
    return {
        "learner_id": learner.public_id,
        "profile_type": ability_profile.get("profile_type", "not_started"),
        "target_domain": learner.target_domain,
        "ability_level": profile_ability_level(ability_profile) if profile else 0,
        "profile_status": "ready" if profile else "not_started",
        "latest_profile_id": profile.public_id if profile else None,
        "updated_at": profile.updated_at.isoformat() if profile else None,
    }


class LearnerApiService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = LearnerRepository(db)

    def list(self) -> list[dict[str, Any]]:
        learners = self.repository.list()
        if not learners:
            learners = [get_or_create_demo_learner(self.db, "learner_001")]
            self.db.commit()
        return [serialize_learner_summary(self.db, learner) for learner in learners]

    def create(self, payload: LearnerCreateRequest) -> dict[str, Any]:
        if self.repository.get(payload.learner_id) is not None:
            raise conflict("LEARNER_ALREADY_EXISTS", f"学习者已存在：{payload.learner_id}")
        learner = self.repository.add(
            Learner(
                public_id=payload.learner_id,
                background=payload.background,
                target_domain=payload.target_domain,
                experience_years=payload.experience_years,
                learning_style=payload.learning_style,
            )
        )
        return serialize_learner_summary(self.db, learner)

    def profile(self, learner_id: str) -> dict[str, Any]:
        learner = self.repository.get(learner_id)
        if learner is None and learner_id == "learner_001":
            learner = get_or_create_demo_learner(self.db, learner_id)
            self.db.commit()
        if learner is None:
            raise not_found("LEARNER_NOT_FOUND", f"学习者不存在：{learner_id}")
        return serialize_profile_detail(self.db, learner)
