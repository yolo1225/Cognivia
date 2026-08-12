from datetime import UTC, datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.security import Principal, hash_password, require_admin
from app.models import Learner, User
from app.schemas.common import ApiResponse, ok
from app.services.session_service import session_store

router=APIRouter()
class StatusBody(BaseModel): status:str=Field(pattern=r"^(active|disabled)$")
class PasswordBody(BaseModel): password:str=Field(min_length=8,max_length=72)
def data(db,user):
    learner=db.get(Learner,user.learner_id) if user.learner_id else None
    return {"user_id":user.public_id,"username":user.username,"display_name":user.display_name,"role":user.role,"status":user.status,"learner_id":learner.public_id if learner else None,"created_at":user.created_at}
def find(db,user_id):
    user=db.scalar(select(User).where(User.public_id==user_id))
    if not user: raise HTTPException(404,"用户不存在")
    return user
@router.get("",response_model=ApiResponse)
def users(status:str|None=Query(None),db:Session=Depends(get_db),_p:Principal=Depends(require_admin))->ApiResponse:
    stmt=select(User).order_by(User.role.desc(),User.username.asc()); stmt=stmt.where(User.status==status) if status else stmt
    return ok([data(db,u) for u in db.scalars(stmt)])
@router.patch("/{user_id}/status",response_model=ApiResponse)
def status(user_id:str,body:StatusBody,db:Session=Depends(get_db),p:Principal=Depends(require_admin))->ApiResponse:
    user=find(db,user_id)
    if user.public_id==p.user_id and body.status=="disabled": raise HTTPException(409,"不能禁用当前账号")
    if user.role=="admin" and body.status=="disabled" and db.scalar(select(func.count(User.id)).where(User.role=="admin",User.status=="active"))<=1: raise HTTPException(409,"不能禁用唯一管理员")
    user.status=body.status; db.commit()
    if body.status=="disabled": session_store.revoke_user(user.public_id)
    return ok(data(db,user))
@router.post("/{user_id}/reset-password",response_model=ApiResponse)
def reset(user_id:str,body:PasswordBody,db:Session=Depends(get_db),_p:Principal=Depends(require_admin))->ApiResponse:
    user=find(db,user_id); user.password_hash=hash_password(body.password); user.password_changed_at=datetime.now(UTC); db.commit(); session_store.revoke_user(user.public_id); return ok({"reset":True})
@router.post("/{user_id}/revoke-sessions",response_model=ApiResponse)
def revoke(user_id:str,db:Session=Depends(get_db),_p:Principal=Depends(require_admin))->ApiResponse:
    user=find(db,user_id); session_store.revoke_user(user.public_id); return ok({"revoked":True})
