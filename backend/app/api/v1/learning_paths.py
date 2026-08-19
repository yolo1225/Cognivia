from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import Principal, get_current_user, self_service_learner
from app.schemas.common import ApiResponse, ok
from app.services.learning_path_service import complete_path_node, verify_path_node

router = APIRouter()


class EvidenceRequest(BaseModel):
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)


def _error(exc: ValueError) -> HTTPException:
    code = str(exc).upper()
    status = 409 if code in {"LEARNING_PATH_NODE_LOCKED", "LEARNING_PATH_EVIDENCE_NOT_VERIFIED"} else 404
    return HTTPException(status, code)


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
