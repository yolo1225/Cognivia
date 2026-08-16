from collections.abc import Callable
from typing import TypeVar

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import conflict
from app.repositories.idempotency_repo import IdempotencyRepository


Result = TypeVar("Result", bound=dict)


def execute_idempotent(
    db: Session,
    *,
    scope: str,
    request_key: str,
    operation: Callable[[], tuple[Result, str | None, str | None]],
) -> tuple[Result, bool]:
    """Run a write operation once and return ``(result, replayed)``.

    The row is committed with the domain write, so a browser retry cannot create a
    second task, feedback, or review decision. ``operation`` may flush to obtain
    generated IDs, but it must not commit or roll back the session: this function
    owns the transaction boundary.
    """

    repository = IdempotencyRepository(db)
    existing = repository.get(scope, request_key)
    if existing is not None:
        if existing.status == "completed":
            return dict(existing.result_json or {}), True
        raise conflict("IDEMPOTENCY_REQUEST_IN_PROGRESS", "相同请求正在处理中，请稍后重试。")

    try:
        record = repository.create(scope, request_key)
    except IntegrityError:
        db.rollback()
        existing = repository.get(scope, request_key)
        if existing is not None and existing.status == "completed":
            return dict(existing.result_json or {}), True
        raise conflict("IDEMPOTENCY_REQUEST_IN_PROGRESS", "相同请求正在处理中，请稍后重试。")

    try:
        result, entity_type, entity_public_id = operation()
        repository.complete(
            record,
            entity_type=entity_type,
            entity_public_id=entity_public_id,
            result=result,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result, False
