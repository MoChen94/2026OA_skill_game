"""FastAPI 依赖：当前用户 / 角色权限校验。"""
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from . import models
from .database import get_db
from .security import decode_token

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> models.User:
    if cred is None:
        raise HTTPException(401, "未登录")
    payload = decode_token(cred.credentials)
    if not payload:
        raise HTTPException(401, "登录已过期，请重新登录")
    user = db.get(models.User, int(payload["sub"]))
    if user is None or not user.enabled:
        raise HTTPException(401, "账号不存在或已禁用")
    return user


def require_roles(*roles: str, module: str | None = None):
    """返回一个依赖：要求当前用户属于给定角色之一，可选同时要求功能模块权限。"""

    def checker(user: models.User = Depends(get_current_user)) -> models.User:
        if user.role not in roles:
            raise HTTPException(403, "当前角色无权执行该操作")
        if module and user.role != models.ROLE_ADMIN and module not in user.modules:
            raise HTTPException(403, f"无权限访问「{models.MODULES.get(module, module)}」模块")
        return user

    return checker


def require_module(module: str):
    """返回一个依赖：要求当前用户拥有指定功能模块权限（管理员始终放行）。"""

    def checker(user: models.User = Depends(get_current_user)) -> models.User:
        if user.role == models.ROLE_ADMIN or module in user.modules:
            return user
        raise HTTPException(403, f"无权限访问「{models.MODULES.get(module, module)}」模块")

    return checker
