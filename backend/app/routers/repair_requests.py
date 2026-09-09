"""报修单接口（两段式）：工程师/孪生提报 → 调度员审核立项（生成正式工单）或驳回。

状态机：待审核 --通过立项--> 已立项(生成工单)
              |--驳回--> 已驳回
              |--报修人撤回--> 已撤回
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import require_module, require_roles
from ..schemas import RepairApproveIn, RepairRejectIn, RepairRequestIn
from ..services import (
    add_log,
    audit,
    gen_order_no,
    gen_request_no,
    notify_and_callback,
    notify_users,
    rr_to_dict,
    wo_to_dict,
)

router = APIRouter(prefix="/repair-requests", tags=["报修管理"])

_MANAGERS = (models.ROLE_ADMIN, models.ROLE_DISPATCHER)


def _get(db: Session, rid: int) -> models.RepairRequest:
    rr = db.get(models.RepairRequest, rid)
    if rr is None:
        raise HTTPException(404, "报修单不存在")
    return rr


def _can_view(user: models.User, rr: models.RepairRequest) -> bool:
    if user.role in _MANAGERS:
        return True
    return rr.creator_id == user.id


# ---------- 提报 ----------

@router.post("")
def create_request(
    payload: RepairRequestIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("repairs")),
):
    if payload.device_id and db.get(models.Device, payload.device_id) is None:
        raise HTTPException(400, "设备不存在")
    if payload.priority not in models.WO_PRIORITIES:
        raise HTTPException(400, "优先级不合法")

    rr = models.RepairRequest(
        request_no=gen_request_no(db),
        title=payload.title,
        device_id=payload.device_id,
        description=payload.description,
        priority=payload.priority,
        creator_id=user.id,
    )
    db.add(rr)
    db.commit()
    db.refresh(rr)
    notify_users(
        db, "repair_created",
        f"{user.real_name} 提交报修 {rr.request_no}：{rr.title}",
        target_roles=_MANAGERS,
        extra={"requestNo": rr.request_no},
    )
    return rr_to_dict(db, rr)


@router.get("")
def list_requests(
    status: str | None = Query(default=None),
    mine: bool = Query(default=False),
    keyword: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("repairs")),
):
    q = db.query(models.RepairRequest)
    if user.role == models.ROLE_ENGINEER or mine:
        q = q.filter(models.RepairRequest.creator_id == user.id)
    if status:
        q = q.filter(models.RepairRequest.status == status)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(
            models.RepairRequest.title.like(like) | models.RepairRequest.request_no.like(like)
        )
    total = q.count()
    items = (
        q.order_by(models.RepairRequest.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {"total": total, "items": [rr_to_dict(db, rr) for rr in items]}


@router.get("/{rid}")
def get_request(
    rid: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("repairs")),
):
    rr = _get(db, rid)
    if not _can_view(user, rr):
        raise HTTPException(403, "无权查看该报修单")
    return rr_to_dict(db, rr)


# ---------- 审核 ----------

@router.post("/{rid}/approve")
def approve(
    rid: int,
    payload: RepairApproveIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*_MANAGERS, module="repairs")),
):
    """审核立项：生成正式工单（可同时指派工程师直接派单）。"""
    rr = _get(db, rid)
    if rr.status != models.RR_PENDING_REVIEW:
        raise HTTPException(400, "当前状态不可审核立项")
    if payload.priority not in models.WO_PRIORITIES:
        raise HTTPException(400, "优先级不合法")
    if payload.order_type not in models.WO_TYPES:
        raise HTTPException(400, "工单类型不合法")

    assignee = None
    if payload.assignee_id:
        assignee = db.get(models.User, payload.assignee_id)
        if assignee is None or assignee.role != models.ROLE_ENGINEER or not assignee.enabled:
            raise HTTPException(400, "指派的工程师不存在或不可用")

    order = models.WorkOrder(
        order_no=gen_order_no(db),
        title=rr.title,
        order_type=payload.order_type,
        device_id=rr.device_id,
        description=rr.description,
        alarm_data=rr.alarm_data,
        priority=payload.priority,
        creator_id=rr.creator_id,
    )
    if assignee:
        order.assignee_id = assignee.id
        order.dispatcher_id = user.id
        order.dispatch_time = datetime.now()
        order.status = models.WO_PENDING_ACCEPT

    db.add(order)
    db.flush()
    add_log(db, order, user, "CREATE", f"由报修单 {rr.request_no} 审核立项")
    if assignee:
        add_log(db, order, user, "DISPATCH", f"派单给 {assignee.real_name}")

    rr.status = models.RR_APPROVED
    rr.reviewer_id = user.id
    rr.review_comment = payload.review_comment
    rr.review_time = datetime.now()
    rr.work_order_id = order.id
    audit(db, user, "REPAIR_APPROVE", f"报修单 {rr.request_no} 审核立项，生成工单 {order.order_no}")
    db.commit()
    db.refresh(order)

    if assignee:
        notify_and_callback(
            db, order, "dispatched",
            target_ids={assignee.id},
            message=f"收到新工单 {order.order_no}：{order.title}",
        )
    else:
        notify_and_callback(
            db, order, "created",
            target_roles=_MANAGERS,
            message=f"报修单 {rr.request_no} 已立项，工单 {order.order_no} 待派发：{order.title}",
        )
    notify_users(
        db, "repair_approved",
        f"报修单 {rr.request_no} 已审核立项，工单 {order.order_no}",
        target_ids={rr.creator_id} if rr.creator_id else set(),
        extra={"requestNo": rr.request_no, "orderNo": order.order_no},
    )
    return {"request": rr_to_dict(db, rr), "work_order": wo_to_dict(db, order)}


@router.post("/{rid}/reject")
def reject(
    rid: int,
    payload: RepairRejectIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*_MANAGERS, module="repairs")),
):
    rr = _get(db, rid)
    if rr.status != models.RR_PENDING_REVIEW:
        raise HTTPException(400, "当前状态不可驳回")
    rr.status = models.RR_REJECTED
    rr.reviewer_id = user.id
    rr.review_comment = payload.review_comment
    rr.review_time = datetime.now()
    audit(db, user, "REPAIR_REJECT", f"报修单 {rr.request_no} 驳回：{payload.review_comment}")
    db.commit()
    notify_users(
        db, "repair_rejected",
        f"报修单 {rr.request_no} 被驳回：{payload.review_comment or '未说明原因'}",
        target_ids={rr.creator_id} if rr.creator_id else set(),
        extra={"requestNo": rr.request_no},
    )
    return rr_to_dict(db, rr)


@router.post("/{rid}/withdraw")
def withdraw(
    rid: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("repairs")),
):
    rr = _get(db, rid)
    if rr.status != models.RR_PENDING_REVIEW:
        raise HTTPException(400, "仅待审核的报修单可撤回")
    if rr.creator_id != user.id:
        raise HTTPException(403, "只能撤回自己提交的报修单")
    rr.status = models.RR_WITHDRAWN
    rr.review_time = datetime.now()
    db.commit()
    notify_users(
        db, "repair_withdrawn",
        f"报修单 {rr.request_no} 已被报修人撤回",
        target_roles=_MANAGERS,
        extra={"requestNo": rr.request_no},
    )
    return rr_to_dict(db, rr)
