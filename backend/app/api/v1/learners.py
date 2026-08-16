from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import (
    Principal,
    assert_learner_access,
    get_current_user,
    require_admin,
    self_service_learner,
)
from app.models import Learner
from app.schemas.common import ApiResponse, ok
from app.services.learner_service import get_or_create_demo_learner
from app.services.profile_service import (
    is_initial_profile_ready,
    latest_profile_for_learner,
    profile_ability_level,
    serialize_profile_detail,
)

router = APIRouter()


class LearnerCreate(BaseModel):
    learner_id: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    background: str = Field(default="", max_length=255)
    target_domain: str = Field(default="ai_app_dev", min_length=1, max_length=64)
    experience_years: int = Field(default=0, ge=0, le=50)
    learning_style: str = Field(default="mixed", pattern=r"^(theory|practice|mixed)$")

    @field_validator("learner_id", "background", "target_domain", "learning_style", mode="before")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return str(value).strip()


INITIAL_DIRECTIONS = {
    "llm_application",
    "prompt_engineering",
    "rag_knowledge_base",
    "agent_orchestration",
}
INITIAL_EDUCATION_LEVELS = {"中职/高中", "专科", "本科", "硕士及以上"}


class InitialContextUpdate(BaseModel):
    education_level: str = Field(min_length=1, max_length=64)
    major: str = Field(min_length=1, max_length=128)
    experience_years: int = Field(ge=0, le=50)
    learning_style: str = Field(pattern=r"^(theory|practice|mixed)$")
    direction_tags: list[str] = Field(min_length=1, max_length=3)

    @field_validator("education_level", "major", mode="before")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("education_level")
    @classmethod
    def validate_education_level(cls, value: str) -> str:
        if value not in INITIAL_EDUCATION_LEVELS:
            raise ValueError("invalid education_level")
        return value

    @field_validator("direction_tags")
    @classmethod
    def validate_direction_tags(cls, value: list[str]) -> list[str]:
        normalized = [str(item).strip() for item in value]
        if len(set(normalized)) != len(normalized) or any(item not in INITIAL_DIRECTIONS for item in normalized):
            raise ValueError("invalid direction_tags")
        return normalized


def serialize_learner_summary(db: Session, learner: Learner) -> dict[str, Any]:
    profile = latest_profile_for_learner(db, learner)
    ability_profile = profile.ability_profile_json if profile else {}
    return {
        "learner_id": learner.public_id,
        "profile_type": ability_profile.get("profile_type", "not_started"),
        "target_domain": learner.target_domain,
        "ability_level": profile_ability_level(ability_profile) if profile else 0,
        "profile_status": "ready" if is_initial_profile_ready(profile) else "not_started",
        "latest_profile_id": profile.public_id if profile else None,
        "updated_at": profile.updated_at.isoformat() if profile else None,
    }


@router.get("", response_model=ApiResponse)
def list_learners(db: Session = Depends(get_db), principal: Principal = Depends(get_current_user)) -> ApiResponse:
    if principal.role != "admin" and principal.learner_id:
        learner = db.scalar(select(Learner).where(Learner.public_id == principal.learner_id))
        return ok([serialize_learner_summary(db, learner)] if learner else [])
    learners = list(db.scalars(select(Learner).order_by(Learner.public_id)))
    if not learners:
        learners = [get_or_create_demo_learner(db, "learner_001")]
        db.commit()

    return ok([serialize_learner_summary(db, learner) for learner in learners])


@router.post("", response_model=ApiResponse)
def create_learner(payload: LearnerCreate, db: Session = Depends(get_db), _principal: Principal = Depends(require_admin)) -> ApiResponse:
    duplicate = db.scalar(select(Learner).where(Learner.public_id == payload.learner_id))
    if duplicate is not None:
        raise HTTPException(status_code=409, detail=f"Learner already exists: {payload.learner_id}")

    learner = Learner(
        public_id=payload.learner_id,
        background=payload.background,
        target_domain=payload.target_domain,
        experience_years=payload.experience_years,
        learning_style=payload.learning_style,
    )
    db.add(learner)
    db.commit()
    db.refresh(learner)
    return ok(serialize_learner_summary(db, learner))


@router.put("/{learner_id}/initial-context", response_model=ApiResponse)
def update_initial_context(
    learner_id: str,
    payload: InitialContextUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    resolved_learner_id = self_service_learner(principal, learner_id)
    learner = db.scalar(select(Learner).where(Learner.public_id == resolved_learner_id))
    if learner is None:
        raise HTTPException(status_code=404, detail="LEARNER_NOT_FOUND")

    learner.education_level = payload.education_level
    learner.major = payload.major
    learner.background = f"{payload.education_level}｜{payload.major}"
    learner.experience_years = payload.experience_years
    learner.learning_style = payload.learning_style
    learner.direction_tags_json = payload.direction_tags
    learner.target_domain = "ai_app_dev"
    db.commit()

    return ok(
        {
            "learner_id": learner.public_id,
            "education_level": learner.education_level,
            "major": learner.major,
            "background": learner.background,
            "experience_years": learner.experience_years,
            "learning_style": learner.learning_style,
            "target_domain": learner.target_domain,
            "direction_tags": learner.direction_tags_json or [],
            "context_complete": True,
        }
    )


@router.get("/{learner_id}/profile", response_model=ApiResponse)
def get_learner_profile(learner_id: str, db: Session = Depends(get_db), principal: Principal = Depends(get_current_user)) -> ApiResponse:
    assert_learner_access(principal, learner_id)
    learner = db.scalar(select(Learner).where(Learner.public_id == learner_id))
    if learner is None:
        if learner_id == "learner_001":
            learner = get_or_create_demo_learner(db, learner_id)
            db.commit()
        else:
            raise HTTPException(status_code=404, detail=f"Learner not found: {learner_id}")
    return ok(serialize_profile_detail(db, learner))
