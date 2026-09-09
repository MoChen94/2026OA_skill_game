"""保养计划：计划管理 + 到期自动生成保养工单（后台扫描 + 手动触发）。"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import require_module, require_roles
from ..schemas import MaintenancePlanIn
from ..services import ACTIVE_STATUSES, add_log, audit, gen_order_no, notify_and_callback

router = APIRouter(prefix="/maintenance-plans", tags=["保养计划"])

_MANAGERS = (models.ROLE_ADMIN, models.ROLE_DISPATCHER)


def _to_dict(db: Session, p: models.MaintenancePlan) -> dict:
    active_wo = (
        db.query(models.WorkOrder)
        .filter(
            models.WorkOrder.plan_id == p.id,
            models.WorkOrder.status.in_(ACTIVE_STATUSES),
        )
        .first()
    )
    return {
        "id": p.id,
        "name": p.name,
        "device_id": p.device_id,
        "device_code": p.device.code,
        "device_name": p.device.name,
        "cycle_days": p.cycle_days,
        "next_due_date": p.next_due_date.isoformat(timespec="minutes") if p.next_due_date else None,
        "last_run_date": p.last_run_date.isoformat(timespec="minutes") if p.last_run_date else None,
        "owner_id": p.owner_id,
        "owner_name": p.owner.real_name if p.owner else None,
        "enabled": p.enabled,
        "description": p.description,
        "active_work_order_no": active_wo.order_no if active_wo else None,
    }


def scan_due_plans(db: Session) -> int:
    """到期保养计划 → 自动生成保养工单。返回本次生成的工单数。"""
    today = datetime.now()
    due = (
        db.query(models.MaintenancePlan)
        .filter(models.MaintenancePlan.enabled.is_(True), models.MaintenancePlan.next_due_date <= today)
        .all()
    )
    generated = 0
    for p in due:
        active_wo = (
            db.query(models.WorkOrder)
            .filter(
                models.WorkOrder.plan_id == p.id,
                models.WorkOrder.status.in_(ACTIVE_STATUSES),
            )
            .first()
        )
        if active_wo:
            continue  # 上一周期工单未完结，暂不重复生成
        order = models.WorkOrder(
            order_no=gen_order_no(db),
            title=f"[{p.device.name}] {p.name}（计划保养）",
            order_type="MAINTENANCE",
            device_id=p.device_id,
            plan_id=p.id,
            description=p.description or f"按保养计划自动生成（周期 {p.cycle_days} 天）",
            priority="P3",
            creator_id=None,  # 系统（保养计划）创建
        )
        if p.owner_id:
            owner = db.get(models.User, p.owner_id)
            if owner and owner.enabled and owner.role == models.ROLE_ENGINEER:
                order.assignee_id = owner.id
                order.dispatch_time = datetime.now()
                order.status = models.WO_PENDING_ACCEPT
        db.add(order)
        db.flush()
        add_log(db, order, None, "CREATE", f"按保养计划「{p.name}」自动生成")
        if order.assignee_id:
            add_log(db, order, None, "DISPATCH", f"按计划负责人自动派单给 {p.owner.real_name}")
        p.last_run_date = today
        p.next_due_date = today + timedelta(days=p.cycle_days)
        generated += 1
        if order.assignee_id:
            notify_and_callback(
                db, order, "dispatched",
                target_ids={order.assignee_id},
                message=f"收到保养工单 {order.order_no}：{order.title}",
            )
        else:
            notify_and_callback(
                db, order, "created",
                target_roles=_MANAGERS,
                message=f"保养工单 {order.order_no} 待派发：{order.title}",
            )
    if generated:
        db.commit()
    return generated


@router.get("")
def list_plans(
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("plans")),
):
    plans = db.query(models.MaintenancePlan).order_by(models.MaintenancePlan.next_due_date).all()
    return [_to_dict(db, p) for p in plans]


@router.post("")
def create_plan(
    payload: MaintenancePlanIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*_MANAGERS, module="plans")),
):
    if db.get(models.Device, payload.device_id) is None:
        raise HTTPException(400, "设备不存在")
    if payload.owner_id:
        owner = db.get(models.User, payload.owner_id)
        if owner is None or owner.role != models.ROLE_ENGINEER:
            raise HTTPException(400, "负责人必须是工程师")
    p = models.MaintenancePlan(
        name=payload.name,
        device_id=payload.device_id,
        cycle_days=payload.cycle_days,
        next_due_date=payload.next_due_date or datetime.now(),
        owner_id=payload.owner_id,
        enabled=payload.enabled,
        description=payload.description,
    )
    db.add(p)
    audit(db, user, "PLAN_CREATE", f"新建保养计划 {p.name}（{p.device.name}，周期 {p.cycle_days} 天）")
    db.commit()
    db.refresh(p)
    return _to_dict(db, p)


@router.put("/{pid}")
def update_plan(
    pid: int,
    payload: MaintenancePlanIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*_MANAGERS, module="plans")),
):
    p = db.get(models.MaintenancePlan, pid)
    if p is None:
        raise HTTPException(404, "保养计划不存在")
    if db.get(models.Device, payload.device_id) is None:
        raise HTTPException(400, "设备不存在")
    if payload.owner_id:
        owner = db.get(models.User, payload.owner_id)
        if owner is None or owner.role != models.ROLE_ENGINEER:
            raise HTTPException(400, "负责人必须是工程师")
    p.name = payload.name
    p.device_id = payload.device_id
    p.cycle_days = payload.cycle_days
    if payload.next_due_date:
        p.next_due_date = payload.next_due_date
    p.owner_id = payload.owner_id
    p.enabled = payload.enabled
    p.description = payload.description
    audit(db, user, "PLAN_UPDATE", f"修改保养计划 {p.name}")
    db.commit()
    return _to_dict(db, p)


@router.delete("/{pid}")
def delete_plan(
    pid: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(models.ROLE_ADMIN, module="plans")),
):
    p = db.get(models.MaintenancePlan, pid)
    if p is None:
        raise HTTPException(404, "保养计划不存在")
    audit(db, user, "PLAN_DELETE", f"删除保养计划 {p.name}")
    db.delete(p)
    db.commit()
    return {"ok": True}


@router.post("/{pid}/run-now")
def run_now(
    pid: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*_MANAGERS, module="plans")),
):
    """手动触发：立即按计划生成一张保养工单。"""
    p = db.get(models.MaintenancePlan, pid)
    if p is None:
        raise HTTPException(404, "保养计划不存在")
    active_wo = (
        db.query(models.WorkOrder)
        .filter(
            models.WorkOrder.plan_id == p.id,
            models.WorkOrder.status.in_(ACTIVE_STATUSES),
        )
        .first()
    )
    if active_wo:
        raise HTTPException(400, f"该计划已有进行中的保养工单 {active_wo.order_no}")

    order = models.WorkOrder(
        order_no=gen_order_no(db),
        title=f"[{p.device.name}] {p.name}（计划保养）",
        order_type="MAINTENANCE",
        device_id=p.device_id,
        plan_id=p.id,
        description=p.description or f"按保养计划手动触发（周期 {p.cycle_days} 天）",
        priority="P3",
        creator_id=user.id,
    )
    if p.owner_id:
        owner = db.get(models.User, p.owner_id)
        if owner and owner.enabled and owner.role == models.ROLE_ENGINEER:
            order.assignee_id = owner.id
            order.dispatcher_id = user.id
            order.dispatch_time = datetime.now()
            order.status = models.WO_PENDING_ACCEPT
    db.add(order)
    db.flush()
    add_log(db, order, user, "CREATE", f"按保养计划「{p.name}」手动触发")
    if order.assignee_id:
        add_log(db, order, user, "DISPATCH", f"派单给 {p.owner.real_name}")
    p.last_run_date = datetime.now()
    p.next_due_date = datetime.now() + timedelta(days=p.cycle_days)
    audit(db, user, "PLAN_RUN", f"手动生成保养工单 {order.order_no}")
    db.commit()
    db.refresh(order)
    if order.assignee_id:
        notify_and_callback(
            db, order, "dispatched",
            target_ids={order.assignee_id},
            message=f"收到保养工单 {order.order_no}：{order.title}",
        )
    else:
        notify_and_callback(
            db, order, "created",
            target_roles=_MANAGERS,
            message=f"保养工单 {order.order_no} 待派发：{order.title}",
        )
    return {"work_order": order.order_no, "plan": _to_dict(db, p)}
