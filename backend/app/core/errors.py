from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.common import fail


class DomainError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int = status.HTTP_400_BAD_REQUEST, details: dict | None = None) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)


def not_found(code: str, message: str) -> DomainError:
    return DomainError(code, message, status_code=status.HTTP_404_NOT_FOUND)


def conflict(code: str, message: str) -> DomainError:
    return DomainError(code, message, status_code=status.HTTP_409_CONFLICT)


def validation_error(code: str, message: str, *, details: dict | None = None) -> DomainError:
    return DomainError(
        code,
        message,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        details=details,
    )


def unavailable(code: str, message: str) -> DomainError:
    return DomainError(code, message, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)


def api_error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict | None = None,
) -> JSONResponse:
    payload = fail(code=code, message=message, details=details)
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    message = str(exc.detail) if exc.detail else "HTTP error"
    return api_error_response(
        status_code=exc.status_code,
        code=f"HTTP_{exc.status_code}",
        message=message,
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return api_error_response(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        code="VALIDATION_ERROR",
        message="Request validation failed",
        details={"errors": exc.errors()},
    )


async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    return api_error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )
