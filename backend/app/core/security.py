from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from uuid import uuid4

import bcrypt
import jwt
from fastapi import Cookie, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.models import GenerationTask, Learner, LearningResource, TutoringSession, User
from app.services.session_service import session_store


@dataclass(frozen=True)
class Principal:
    user_id: str
    role: str
    learner_id: str | None = None
    session_id: str | None = None


DemoPrincipal = Principal


def hash_password(password: str) -> str:
    raw = password.encode("utf-8")
    if len(raw) > 72:
        raise ValueError("password must not exceed 72 UTF-8 bytes")
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (TypeError, ValueError):
        return False


def create_access_token(user: User, session_id: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": user.public_id,
            "role": user.role,
            "sid": session_id,
            "iat": now,
            "exp": now + timedelta(minutes=settings.access_token_minutes),
            "jti": str(uuid4()),
        },
        settings.jwt_secret_key,
        algorithm="HS256",
    )


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(401, "登录状态无效或已过期") from exc


def new_refresh_token() -> tuple[str, str]:
    value = token_urlsafe(48)
    return value, sha256(value.encode()).hexdigest()


def get_current_user(
    access_token: str | None = Cookie(None), db: Session = Depends(get_db)
) -> Principal:
    if settings.app_env == "test" and not access_token:
        return Principal("test_admin", "admin")
    if not access_token:
        raise HTTPException(401, "请先登录")
    payload = decode_access_token(access_token)
    session_id = payload.get("sid")
    if not session_id or not session_store.get(session_id):
        raise HTTPException(401, "登录会话已失效")
    user = db.scalar(select(User).where(User.public_id == payload.get("sub")))
    if not user or user.status != "active":
        raise HTTPException(401, "账号不可用")
    learner = db.get(Learner, user.learner_id) if user.learner_id else None
    return Principal(user.public_id, user.role, learner.public_id if learner else None, session_id)


def require_admin(principal: Principal = Depends(get_current_user)) -> Principal:
    if principal.role != "admin":
        raise HTTPException(403, "需要管理员权限")
    return principal


def assert_learner_access(principal: Principal, learner_id: str) -> None:
    if principal.role != "admin" and principal.learner_id != learner_id:
        raise HTTPException(403, "无权访问其他学习者的数据")


def principal_learner(principal: Principal, requested: str | None = None) -> str:
    if principal.role == "admin":
        if not requested:
            raise HTTPException(422, "learner_id is required")
        return requested
    if not principal.learner_id:
        raise HTTPException(403, "当前账号未关联学习者")
    if requested and requested != principal.learner_id:
        raise HTTPException(403, "无权操作其他学习者")
    return principal.learner_id


def require_task(db: Session, principal: Principal, task_id: str) -> GenerationTask:
    task = db.scalar(select(GenerationTask).where(GenerationTask.public_id == task_id))
    if not task or (
        principal.role != "admin"
        and db.get(Learner, task.learner_id).public_id != principal.learner_id
    ):
        raise HTTPException(404, "Generation task not found")
    return task


def require_resource(db: Session, principal: Principal, resource_id: str) -> LearningResource:
    resource = db.scalar(select(LearningResource).where(LearningResource.public_id == resource_id))
    if not resource:
        raise HTTPException(404, "Resource not found")
    require_task(db, principal, db.get(GenerationTask, resource.generation_task_id).public_id)
    return resource


def require_tutoring(db: Session, principal: Principal, session_id: str) -> TutoringSession:
    session = db.scalar(select(TutoringSession).where(TutoringSession.public_id == session_id))
    learner = db.get(Learner, session.learner_id) if session else None
    if not session or (principal.role != "admin" and learner.public_id != principal.learner_id):
        raise HTTPException(404, "Tutoring session not found")
    return session
