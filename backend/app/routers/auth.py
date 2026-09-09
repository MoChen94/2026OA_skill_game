"""认证接口：登录（失败锁定 + 审计）/ 当前用户 / 修改密码。"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user
from ..schemas import ChangePasswordIn, LoginIn
from ..security import (
    clear_failures,
    create_token,
    hash_password,
    is_locked,
    register_failure,
    verify_password,
)
from ..services import audit, user_to_dict

router = APIRouter(prefix="/auth", tags=["认证"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


@router.post("/login")
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)):
    ip = _client_ip(request)
    locked, remain = is_locked(payload.username)
    if locked:
        audit(db, None, "LOGIN_LOCKED", f"账号 {payload.username} 处于锁定状态，登录被拒", ip)
        db.commit()
        raise HTTPException(423, f"登录失败次数过多，账号已锁定，请 {remain // 60 + 1} 分钟后重试")

    user = db.query(models.User).filter(models.User.username == payload.username).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        register_failure(payload.username)
        audit(db, None, "LOGIN_FAIL", f"用户 {payload.username} 登录失败", ip)
        db.commit()
        raise HTTPException(401, "用户名或密码错误")
    if not user.enabled:
        audit(db, user, "LOGIN_DENIED", "账号已禁用，登录被拒", ip)
        db.commit()
        raise HTTPException(403, "账号已禁用")

    clear_failures(payload.username)
    audit(db, user, "LOGIN_SUCCESS", "登录成功", ip)
    db.commit()
    return {"token": create_token(user), "user": user_to_dict(user)}


@router.get("/me")
def me(user: models.User = Depends(get_current_user)):
    return user_to_dict(user)


@router.post("/change-password")
def change_password(
    payload: ChangePasswordIn,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    if not verify_password(payload.old_password, user.password_hash):
        raise HTTPException(400, "原密码错误")
    user.password_hash = hash_password(payload.new_password)
    audit(db, user, "CHANGE_PASSWORD", "修改了自己的登录密码", _client_ip(request))
    db.commit()
    return {"ok": True}
