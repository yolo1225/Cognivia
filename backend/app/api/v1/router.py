from fastapi import APIRouter, Depends
from app.core.security import get_current_user, require_admin

from app.api.v1 import (
    auth,
    admin_users,
    diagnostics,
    domains,
    evaluations,
    generation_tasks,
    health,
    knowledge,
    knowledge_documents,
    learners,
    learning_packages,
    model_settings,
    reports,
    resources,
    tutoring,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(admin_users.router, prefix="/admin/users", tags=["admin-users"])
api_router.include_router(
    model_settings.router,
    prefix="/admin/model-settings",
    tags=["model-settings"],
    dependencies=[Depends(require_admin)],
)
api_router.include_router(learners.router, prefix="/learners", tags=["learners"], dependencies=[Depends(get_current_user)])
api_router.include_router(diagnostics.router, prefix="/diagnostics", tags=["diagnostics"], dependencies=[Depends(get_current_user)])
api_router.include_router(knowledge.router, prefix="/knowledge", tags=["knowledge"], dependencies=[Depends(require_admin)])
api_router.include_router(
    knowledge_documents.router, prefix="/knowledge/documents", tags=["knowledge-documents"], dependencies=[Depends(require_admin)]
)
api_router.include_router(generation_tasks.router, prefix="/generation-tasks", tags=["generation-tasks"], dependencies=[Depends(get_current_user)])
api_router.include_router(learning_packages.router, prefix="/learning-packages", tags=["learning-packages"], dependencies=[Depends(get_current_user)])
api_router.include_router(resources.router, prefix="/resources", tags=["resources"], dependencies=[Depends(get_current_user)])
api_router.include_router(tutoring.router, prefix="/tutoring", tags=["tutoring"], dependencies=[Depends(get_current_user)])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"], dependencies=[Depends(get_current_user)])
api_router.include_router(domains.router, prefix="/domains", tags=["domains"], dependencies=[Depends(get_current_user)])
api_router.include_router(evaluations.router, prefix="/evaluations", tags=["evaluations"], dependencies=[Depends(require_admin)])
