from contextlib import asynccontextmanager
from threading import Thread

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import DomainError
from app.core.errors import domain_error_handler
from app.core.errors import http_exception_handler
from app.core.errors import validation_exception_handler


def _load_model_config_overrides() -> None:
    """Apply DB-backed model overrides on top of ``.env``/process env values."""
    try:
        from app.services.model_config_service import reload_from_db

        reload_from_db()
    except Exception:
        # The table may not exist yet on a fresh volume (migrations run after
        # first boot); env remains the effective source until then.
        pass


def _recover_interrupted_generation() -> None:
    """Resume checkpoint-backed work without delaying application startup."""

    from app.workers.generation_worker import (
        recover_interrupted_generation_tasks,
        run_generation_task,
    )

    task_ids = recover_interrupted_generation_tasks()
    if not task_ids:
        return

    def resume_claimed_tasks() -> None:
        for task_id in task_ids:
            run_generation_task(task_id)

    Thread(
        target=resume_claimed_tasks,
        name="generation-checkpoint-recovery",
        daemon=True,
    ).start()


def create_app() -> FastAPI:
    settings.validate_auth_config()
    from app.agents.prompt_registry import validate_production_prompts

    validate_production_prompts()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        _load_model_config_overrides()
        try:
            from app.services.candidate_index_job import mark_interrupted_on_startup

            mark_interrupted_on_startup()
        except Exception:
            # The job table may not exist yet on a fresh volume (migrations run
            # after first boot); stale-running cleanup is best effort.
            pass
        try:
            _recover_interrupted_generation()
        except Exception:
            # Fresh databases may not have the generation/checkpoint tables yet.
            # Once migrations exist, interrupted tasks are claimed atomically by
            # their persisted retry state and resumed at most once.
            pass
        yield

    app = FastAPI(
        title=settings.app_name,
        version=settings.schema_version,
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin, "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next):
        public_auth = request.url.path.endswith(("/auth/login", "/auth/register", "/auth/refresh"))
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not public_auth and settings.app_env != "test":
            cookie = request.cookies.get("csrf_token")
            if not cookie or cookie != request.headers.get("X-CSRF-Token"):
                return JSONResponse(status_code=403, content={"schema_version": settings.schema_version, "request_id": str(__import__('uuid').uuid4()), "data": None, "error": {"code": "FORBIDDEN", "message": "CSRF 校验失败", "details": None}})
        return await call_next(request)

    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(DomainError, domain_error_handler)

    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
