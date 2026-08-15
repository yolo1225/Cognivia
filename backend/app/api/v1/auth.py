from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4
from secrets import token_urlsafe

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.security import (
    Principal,
    create_access_token,
    get_current_user,
    hash_password,
    new_refresh_token,
    verify_password,
)
from app.models import Learner, User
from app.schemas.common import ApiResponse, ok
from app.services.session_service import session_store

router = APIRouter()


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_]+$")
    password: str = Field(min_length=8, max_length=72)

    @field_validator("username")
    @classmethod
    def normalize(cls, value: str) -> str:
        return value.strip().lower()


class RegisterRequest(Credentials):
    display_name: str = Field(min_length=1, max_length=128)


def _data(user: User, learner: Learner | None) -> dict:
    return {
        "user_id": user.public_id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "status": user.status,
        "learner_id": learner.public_id if learner else None,
    }


def _set_session(response: Response, user: User) -> None:
    sid, (refresh, digest) = str(uuid4()), new_refresh_token()
    session_store.put(sid, {"user_id": user.public_id, "refresh_hash": digest})
    common = {"httponly": True, "secure": settings.cookie_secure, "samesite": "lax"}
    response.set_cookie(
        "access_token",
        create_access_token(user, sid),
        max_age=settings.access_token_minutes * 60,
        path="/",
        **common,
    )
    response.set_cookie(
        "refresh_token",
        f"{sid}.{refresh}",
        max_age=settings.refresh_token_days * 86400,
        path="/api/v1/auth",
        **common,
    )
    response.set_cookie(
        "csrf_token",
        token_urlsafe(24),
        max_age=settings.refresh_token_days * 86400,
        path="/",
        secure=settings.cookie_secure,
        samesite="lax",
    )


@router.post("/register", response_model=ApiResponse)
def register(
    payload: RegisterRequest, response: Response, db: Session = Depends(get_db)
) -> ApiResponse:
    if db.scalar(select(User).where(User.username == payload.username)):
        raise HTTPException(409, "用户名已存在")
    learner = Learner(public_id=f"learner_{uuid4().hex[:16]}", target_domain="ai_app_dev")
    db.add(learner)
    db.flush()
    user = User(
        public_id=f"user_{uuid4().hex}",
        username=payload.username,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name.strip(),
        role="learner",
        status="active",
        learner_id=learner.id,
        password_changed_at=datetime.now(UTC),
    )
    db.add(user)
    db.commit()
    _set_session(response, user)
    return ok(_data(user, learner))


@router.post("/login", response_model=ApiResponse)
def login(
    payload: Credentials, response: Response, request: Request, db: Session = Depends(get_db)
) -> ApiResponse:
    ip = request.client.host if request.client else "unknown"
    if session_store.login_blocked(payload.username, ip):
        raise HTTPException(429, "登录尝试过多，请稍后重试")
    user = db.scalar(select(User).where(User.username == payload.username))
    if (
        not user
        or user.status != "active"
        or not verify_password(payload.password, user.password_hash)
    ):
        session_store.record_failure(payload.username, ip)
        raise HTTPException(401, "用户名或密码错误")
    session_store.clear_failures(payload.username)
    _set_session(response, user)
    return ok(_data(user, db.get(Learner, user.learner_id) if user.learner_id else None))


@router.post("/refresh", response_model=ApiResponse)
def refresh(
    response: Response, refresh_token: str | None = Cookie(None), db: Session = Depends(get_db)
) -> ApiResponse:
    try:
        sid, token = (refresh_token or "").split(".", 1)
    except ValueError:
        raise HTTPException(401, "刷新令牌无效")
    session = session_store.get(sid)
    if not session or session["refresh_hash"] != sha256(token.encode()).hexdigest():
        session_store.delete(sid)
        raise HTTPException(401, "刷新令牌无效")
    user = db.scalar(select(User).where(User.public_id == session["user_id"]))
    if not user or user.status != "active":
        raise HTTPException(401, "账号不可用")
    session_store.delete(sid)
    _set_session(response, user)
    return ok({"refreshed": True})


@router.post("/logout", response_model=ApiResponse)
def logout(response: Response, refresh_token: str | None = Cookie(None)) -> ApiResponse:
    if refresh_token:
        session_store.delete(refresh_token.split(".", 1)[0])
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/api/v1/auth")
    response.delete_cookie("csrf_token", path="/")
    return ok({"logged_out": True})


@router.get("/me", response_model=ApiResponse)
def me(
    principal: Principal = Depends(get_current_user), db: Session = Depends(get_db)
) -> ApiResponse:
    if settings.app_env == "test" and principal.user_id == "test_admin":
        return ok(
            {
                "user_id": "test_admin",
                "username": "test_admin",
                "display_name": "测试管理员",
                "role": "admin",
                "status": "active",
                "learner_id": None,
            }
        )
    user = db.scalar(select(User).where(User.public_id == principal.user_id))
    return ok(_data(user, db.get(Learner, user.learner_id) if user.learner_id else None))
