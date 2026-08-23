from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import Principal, get_current_user, self_service_learner
from app.schemas.common import ApiResponse, ok
from app.services.learning_path_service import (
    answer_path_node_assessment,
    complete_path_node,
    start_path_node_assessment,
    verify_path_node,
)
from app.workers.generation_worker import run_generation_task

router = APIRouter()


class EvidenceRequest(BaseModel):
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)


class AssessmentAnswerRequest(BaseModel):
    answer: Any


def _error(exc: ValueError) -> HTTPException:
    code = str(exc).upper()
    status = (
        422
        if code == "INVALID_SINGLE_CHOICE_ANSWER"
        else 409
        if code in {
            "LEARNING_PATH_NODE_LOCKED",
            "LEARNING_PATH_EVIDENCE_NOT_VERIFIED",
            "LEARNING_PATH_ASSESSMENT_UNAVAILABLE",
            "PATH_NODE_CHANGED",
        }
        else 404
    )
    return HTTPException(status, code)


@router.post("/{path_id}/nodes/{node_id}/assessments", response_model=ApiResponse)
def start_node_assessment(
    path_id: str,
    node_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    try:
        return ok(
            start_path_node_assessment(
                db,
                path_id=path_id,
                node_id=node_id,
                learner_public_id=self_service_learner(principal),
            )
        )
    except ValueError as exc:
        raise _error(exc) from exc


@router.post(
    "/{path_id}/nodes/{node_id}/assessments/{assessment_id}/answer",
    response_model=ApiResponse,
)
def answer_node_assessment(
    path_id: str,
    node_id: str,
    assessment_id: str,
    payload: AssessmentAnswerRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    try:
        result, task = answer_path_node_assessment(
            db,
            path_id=path_id,
            node_id=node_id,
            assessment_id=assessment_id,
            learner_public_id=self_service_learner(principal),
            answer=payload.answer,
        )
        if task is not None:
            background_tasks.add_task(run_generation_task, task.public_id)
        return ok(result)
    except ValueError as exc:
        raise _error(exc) from exc


@router.post("/{path_id}/nodes/{node_id}/verify", response_model=ApiResponse)
def verify_node(
    path_id: str,
    node_id: str,
    payload: EvidenceRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    try:
        result = verify_path_node(
            db,
            path_id=path_id,
            node_id=node_id,
            learner_public_id=self_service_learner(principal),
            evidence_ids=payload.evidence_ids or None,
        )
        db.commit()
        return ok(result)
    except ValueError as exc:
        raise _error(exc) from exc


@router.post("/{path_id}/nodes/{node_id}/complete", response_model=ApiResponse)
def complete_node(
    path_id: str,
    node_id: str,
    payload: EvidenceRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    if not payload.evidence_ids:
        raise HTTPException(422, "EVIDENCE_IDS_REQUIRED")
    try:
        return ok(
            complete_path_node(
                db,
                path_id=path_id,
                node_id=node_id,
                learner_public_id=self_service_learner(principal),
                evidence_ids=payload.evidence_ids,
            )
        )
    except ValueError as exc:
        raise _error(exc) from exc
