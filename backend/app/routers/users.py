"""用户与部门接口：列表 / 新增 / 修改（权限划分）/ 重置密码。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import require_roles
from ..schemas import ResetPasswordIn, UserCreateIn, UserUpdateIn
from ..security import hash_password
from ..services import audit, user_to_dict

router = APIRouter(tags=["组织与用户"])


def _valid_permissions(permissions: list[str] | None, role: str) -> list[str] | None:
    """校验模块键合法性；None 表示未传（由调用方按角色给默认）。"""
    if permissions is None:
        return None
    for m in permissions:
        if m not in models.MODULES:
            raise HTTPException(400, f"模块 {m} 不存在")
    if role == models.ROLE_ADMIN:
        return list(models.MODULES.keys())  # 管理员固定拥有全部模块
    return list(dict.fromkeys(permissions))


@router.get("/departments")
def list_departments(
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(models.ROLE_ADMIN, models.ROLE_DISPATCHER)),
):
    depts = db.query(models.Department).order_by(models.Department.id).all()
    return [
        {"id": d.id, "name": d.name, "description": d.description, "member_count": len(d.users)}
        for d in depts
    ]


@router.get("/users")
def list_users(
    role: str | None = Query(default=None),
    dept_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(models.ROLE_ADMIN, models.ROLE_DISPATCHER)),
):
    q = db.query(models.User)
    if role:
        q = q.filter(models.User.role == role)
    if dept_id:
        q = q.filter(models.User.dept_id == dept_id)
    return [user_to_dict(u) for u in q.order_by(models.User.id).all()]


@router.post("/users")
def create_user(
    payload: UserCreateIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(models.ROLE_ADMIN)),
):
    if payload.role not in models.ROLE_LABELS:
        raise HTTPException(400, "角色不合法")
    if db.query(models.User).filter(models.User.username == payload.username).first():
        raise HTTPException(400, "用户名已存在")
    perms = _valid_permissions(payload.permissions, payload.role)
    if perms is None:
        perms = models.DEFAULT_MODULES[payload.role]
    new_user = models.User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        real_name=payload.real_name,
        role=payload.role,
        title=payload.title,
        phone=payload.phone,
        dept_id=payload.dept_id,
        permissions=",".join(perms),
    )
    db.add(new_user)
    audit(db, user, "USER_CREATE", f"创建用户 {payload.username}（{payload.real_name}）")
    db.commit()
    return user_to_dict(new_user)


@router.put("/users/{user_id}")
def update_user(
    user_id: int,
    payload: UserUpdateIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(models.ROLE_ADMIN)),
):
    """管理员划分用户权限：角色、岗位、模块权限、启用状态。"""
    if payload.role not in models.ROLE_LABELS:
        raise HTTPException(400, "角色不合法")
    target = db.get(models.User, user_id)
    if target is None:
        raise HTTPException(404, "用户不存在")

    if target.id == user.id:
        # 保护：管理员不能改掉自己的角色/权限/启用状态
        target.real_name = payload.real_name or target.real_name
        target.title = payload.title
        target.phone = payload.phone
        audit(db, user, "USER_UPDATE", f"修改自己档案：{target.real_name}")
        db.commit()
        return user_to_dict(target)

    target.real_name = payload.real_name or target.real_name
    target.title = payload.title
    target.phone = payload.phone
    target.enabled = payload.enabled
    target.role = payload.role

    perms = _valid_permissions(payload.permissions, payload.role)
    if perms is None:
        perms = models.DEFAULT_MODULES[payload.role]
    target.permissions = ",".join(perms)
    audit(db, user, "USER_UPDATE", f"修改用户 {target.username}：角色 {target.role}，权限 {target.permissions}，启用 {target.enabled}")
    db.commit()
    return user_to_dict(target)


@router.put("/users/{user_id}/reset-password")
def reset_password(
    user_id: int,
    payload: ResetPasswordIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(models.ROLE_ADMIN)),
):
    target = db.get(models.User, user_id)
    if target is None:
        raise HTTPException(404, "用户不存在")
    target.password_hash = hash_password(payload.new_password)
    audit(db, user, "USER_RESET_PASSWORD", f"重置用户 {target.username} 的密码")
    db.commit()
    return {"ok": True}
