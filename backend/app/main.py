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


def create_app() -> FastAPI:
    settings.validate_auth_config()
    app = FastAPI(
        title=settings.app_name,
        version=settings.schema_version,
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
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
