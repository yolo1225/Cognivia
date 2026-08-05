from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas.common import ApiResponse, ok
from app.services.report_api_service import ReportApiService

router = APIRouter()


@router.get("/learners/{learner_id}", response_model=ApiResponse)
def get_learning_report(learner_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    return ok(ReportApiService(db).build(learner_id))
