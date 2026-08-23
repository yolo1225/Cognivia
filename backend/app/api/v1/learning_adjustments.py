from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import Principal, get_current_user, self_service_learner
from app.schemas.common import ApiResponse, ok
from app.services.learning_adjustment_service import decide_proposal_resource
from app.workers.generation_worker import run_generation_task


router = APIRouter()


class ResourceDecisionRequest(BaseModel):
    decision: Literal["generate", "skip"]


@router.post("/{proposal_id}/resource-decision", response_model=ApiResponse)
def decide_adjustment_resource(
    proposal_id: str,
    payload: ResourceDecisionRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> ApiResponse:
    try:
        result, task = decide_proposal_resource(
            db,
            proposal_id=proposal_id,
            learner_public_id=self_service_learner(principal),
            decision=payload.decision,
        )
    except ValueError as exc:
        code = str(exc).upper()
        status = 422 if code == "INVALID_RESOURCE_DECISION" else 409
        if code == "LEARNING_ADJUSTMENT_PROPOSAL_NOT_FOUND":
            status = 404
        raise HTTPException(status_code=status, detail=code) from exc
    if task is not None and task.status == "pending":
        background_tasks.add_task(run_generation_task, task.public_id)
    return ok(result)
