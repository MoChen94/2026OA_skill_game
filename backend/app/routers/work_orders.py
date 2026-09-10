"""工单核心接口：创建 / 派单 / 接单 / 完成 / 验收 / 取消，及数字孪生对接。

状态机：
  待派发 --派单--> 待接单 --接单--> 处理中 --提交完成--> 待验收
    |                                                      |
    +------- 验收驳回 -------------------------------------+
    待验收 --验收通过--> 已完成
"""
import json
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from openpyxl import Workbook
from sqlalchemy.orm import Session

from .. import config, models
from ..database import get_db
from ..deps import require_module, require_roles
from ..excel_utils import style_header, xlsx_response
from ..schemas import (
    CancelIn,
    CompleteIn,
    DispatchIn,
    VerifyIn,
    WorkOrderCreateIn,
    WorkOrderExternalIn,
)
from ..services import (
    ACTION_LABELS,
    ACTIVE_STATUSES,
    add_log,
    gen_order_no,
    gen_request_no,
    audit,
    notify_and_callback,
    notify_users,
    rr_to_dict,
    twin_log,
    wo_to_dict,
)

router = APIRouter(prefix="/work-orders", tags=["工单管理"])

_MANAGERS = (models.ROLE_ADMIN, models.ROLE_DISPATCHER)

# 各流转动作允许的当前状态
_ALLOWED = {
    "dispatch": {models.WO_PENDING_DISPATCH},
    "accept": {models.WO_PENDING_ACCEPT},
    "complete": {models.WO_PROCESSING},
    "verify": {models.WO_PENDING_VERIFY},
    "cancel": {models.WO_PENDING_DISPATCH, models.WO_PENDING_ACCEPT},
}


def _get_order(db: Session, order_id: int) -> models.WorkOrder:
    order = db.get(models.WorkOrder, order_id)
    if order is None:
        raise HTTPException(404, "工单不存在")
    return order


def _can_view(user: models.User, order: models.WorkOrder) -> bool:
    if user.role in _MANAGERS:
        return True
    return user.id in (order.creator_id, order.assignee_id)


@router.get("")
def list_orders(
    status: str | None = Query(default=None),
    mine: bool = Query(default=False),
    keyword: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("orders")),
):
    q = db.query(models.WorkOrder)
    if user.role == models.ROLE_ENGINEER or mine:
        # 与我相关 = 指派给我 / 我创建 / 我派发（调度员派别人的单也要跟踪反馈）
        q = q.filter(
            (models.WorkOrder.assignee_id == user.id)
            | (models.WorkOrder.creator_id == user.id)
            | (models.WorkOrder.dispatcher_id == user.id)
        )
    if status:
        q = q.filter(models.WorkOrder.status == status)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(
            models.WorkOrder.title.like(like) | models.WorkOrder.order_no.like(like)
        )
    total = q.count()
    items = (
        q.order_by(models.WorkOrder.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {"total": total, "items": [wo_to_dict(db, wo) for wo in items]}


@router.delete("/all")
def clear_all_orders(
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(models.ROLE_ADMIN)),
):
    """清空全部工单（连带流转日志、报修单、工单附件），仅管理员。"""
    from .files import _file_dir
    files = db.query(models.FileRecord).filter(models.FileRecord.category == "ORDER").all()
    for f in files:
        (_file_dir() / f.stored_name).unlink(missing_ok=True)
        db.delete(f)
    n_orders = db.query(models.WorkOrder).count()
    n_rr = db.query(models.RepairRequest).count()
    db.query(models.WorkOrderLog).delete()
    db.query(models.RepairRequest).delete()
    db.query(models.WorkOrder).delete()
    audit(db, user, "ORDER_CLEAR_ALL", f"清空全部工单（工单{n_orders}张、报修单{n_rr}张、附件{len(files)}个）")
    db.commit()
    return {"ok": True, "deleted_orders": n_orders, "deleted_repairs": n_rr, "deleted_files": len(files)}


@router.get("/export")
def export_orders(
    status: str | None = Query(default=None),
    mine: bool = Query(default=False),
    keyword: str = Query(default=""),
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("orders")),
):
    """导出工单明细 Excel（与列表同样的筛选条件）。"""
    q = db.query(models.WorkOrder)
    if user.role == models.ROLE_ENGINEER or mine:
        # 与我相关 = 指派给我 / 我创建 / 我派发（调度员派别人的单也要跟踪反馈）
        q = q.filter(
            (models.WorkOrder.assignee_id == user.id)
            | (models.WorkOrder.creator_id == user.id)
            | (models.WorkOrder.dispatcher_id == user.id)
        )
    if status:
        q = q.filter(models.WorkOrder.status == status)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(
            models.WorkOrder.title.like(like) | models.WorkOrder.order_no.like(like)
        )
    orders = q.order_by(models.WorkOrder.id.desc()).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "工单明细"
    ws.append(["工单号", "标题", "类型", "优先级", "设备", "状态",
                "指派工程师", "创建时间", "完成时间"])
    for o in orders:
        ws.append([
            o.order_no, o.title, models.WO_TYPES.get(o.order_type, o.order_type),
            models.WO_PRIORITIES.get(o.priority, o.priority),
            o.device.name if o.device else "—",
            models.WO_STATUS_LABELS.get(o.status, o.status),
            o.assignee.real_name if o.assignee else "—",
            o.created_at.strftime("%Y-%m-%d %H:%M"),
            o.finish_time.strftime("%Y-%m-%d %H:%M") if o.finish_time else "—",
        ])
    style_header(ws)
    for col, w in zip("ABCDEFGHI", [16, 34, 10, 8, 22, 10, 12, 16, 16]):
        ws.column_dimensions[col].width = w

    name = f"工单明细_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return xlsx_response(wb, name)


@router.get("/{order_id}")
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("orders")),
):
    order = _get_order(db, order_id)
    if not _can_view(user, order):
        raise HTTPException(403, "无权查看该工单")
    return wo_to_dict(db, order)


@router.get("/{order_id}/logs")
def get_order_logs(
    order_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("orders")),
):
    order = _get_order(db, order_id)
    if not _can_view(user, order):
        raise HTTPException(403, "无权查看该工单")
    return [
        {
            "action": log.action,
            "action_label": ACTION_LABELS.get(log.action, log.action),
            "detail": log.detail,
            "operator_name": log.operator.real_name if log.operator else "系统",
            "created_at": log.created_at.isoformat(timespec="seconds"),
        }
        for log in order.logs
    ]


# ---------- 创建 ----------

@router.post("")
def create_order(
    payload: WorkOrderCreateIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("orders")),
):
    if payload.device_id and db.get(models.Device, payload.device_id) is None:
        raise HTTPException(400, "设备不存在")
    if payload.priority not in models.WO_PRIORITIES:
        raise HTTPException(400, "优先级不合法")
    if payload.order_type not in models.WO_TYPES:
        raise HTTPException(400, "工单类型不合法")
    if user.role == models.ROLE_ENGINEER:
        # 两段式：工程师通过报修管理提报，由调度员审核立项
        raise HTTPException(403, "工程师请通过「报修管理」提报，由调度员审核立项后生成工单")

    order = models.WorkOrder(
        order_no=gen_order_no(db),
        title=payload.title,
        order_type=payload.order_type,
        device_id=payload.device_id,
        description=payload.description,
        priority=payload.priority,
        creator_id=user.id,
    )

    if payload.assignee_id:
        assignee = db.get(models.User, payload.assignee_id)
        if assignee is None or assignee.role != models.ROLE_ENGINEER or not assignee.enabled:
            raise HTTPException(400, "指派的工程师不存在或不可用")
        order.assignee_id = assignee.id
        order.dispatcher_id = user.id
        order.dispatch_time = datetime.now()
        order.status = models.WO_PENDING_ACCEPT

    db.add(order)
    db.flush()

    if payload.assignee_id:
        add_log(db, order, user, "CREATE", "创建工单")
        add_log(db, order, user, "DISPATCH", f"派单给 {assignee.real_name}")
    else:
        add_log(db, order, user, "CREATE", "创建工单，等待派发")

    # 绑定新建表单里预上传的草稿附件（仅限本人上传的）
    if payload.draft_file_ids:
        drafts = db.query(models.FileRecord).filter(
            models.FileRecord.id.in_(payload.draft_file_ids),
            models.FileRecord.category == "DRAFT",
            models.FileRecord.uploader_id == user.id,
        ).all()
        for f in drafts:
            f.order_id = order.id
            f.category = "ORDER"
    db.commit()
    db.refresh(order)

    if payload.assignee_id:
        notify_and_callback(
            db, order, "dispatched",
            target_ids={payload.assignee_id},
            message=f"收到新工单 {order.order_no}：{order.title}",
        )
    else:
        notify_and_callback(
            db, order, "created",
            target_roles=_MANAGERS,
            message=f"新工单 {order.order_no} 待派发：{order.title}",
        )
    return wo_to_dict(db, order)


@router.post("/external")
def create_order_external(
    payload: WorkOrderExternalIn,
    db: Session = Depends(get_db),
    x_api_key: str | None = Header(default=None),
):
    """数字孪生系统下发工单。白名单模式：局域网内直接调用，无需鉴权（X-API-Key 传不传都行）。"""
    device = db.query(models.Device).filter(models.Device.code == payload.deviceCode).first()
    if device is None:
        raise HTTPException(404, f"设备编号 {payload.deviceCode} 未在设备台账中登记")

    level_map = {1: "P1", 2: "P2", 3: "P3", 4: "P4"}
    title = payload.title or f"[{device.name}] 异常告警"
    description = payload.description or (
        f"数字孪生系统监测到 {device.name}({device.code}) 发生异常"
        f"（告警等级 {payload.alarmLevel}）"
        + (f"，位置：{payload.location}" if payload.location else "")
    )
    alarm_data_json = json.dumps(payload.sensorSnapshot or {}, ensure_ascii=False)
    priority = payload.priority if payload.priority in models.WO_PRIORITIES else level_map.get(payload.alarmLevel, "P3")
    order_type = payload.orderType if payload.orderType in models.WO_TYPES else "FAULT"

    # 孪生端显式指派工程师：视为调度员已审核，直接生成工单并派单
    assignee = None
    if payload.assigneeUsername:
        assignee = db.query(models.User).filter(models.User.username == payload.assigneeUsername).first()
        if assignee is None or assignee.role != models.ROLE_ENGINEER or not assignee.enabled:
            raise HTTPException(400, f"指派的工程师 {payload.assigneeUsername} 不存在或不可用")

    # 分级处理：未指派时，P2~P4 告警生成报修单由调度员审核立项；P1 或已指派 → 直接生成工单
    if assignee is None and payload.alarmLevel >= 2:
        rr = models.RepairRequest(
            request_no=gen_request_no(db),
            title=title,
            device_id=device.id,
            description=description,
            alarm_data=alarm_data_json,
            priority=priority,
            creator_id=None,  # 系统（数字孪生）提报
        )
        db.add(rr)
        db.commit()
        db.refresh(rr)
        twin_log(db, "IN", "孪生下发报修", f"{rr.request_no} {rr.title}（告警等级{payload.alarmLevel}，待调度审核立项）")
        notify_users(
            db, "repair_created",
            f"数字孪生告警，新报修单 {rr.request_no} 待审核：{rr.title}",
            target_roles=_MANAGERS,
            extra={"requestNo": rr.request_no},
        )
        return {"kind": "repair_request", "data": rr_to_dict(db, rr)}

    order = models.WorkOrder(
        order_no=gen_order_no(db),
        title=title,
        order_type=order_type,
        device_id=device.id,
        description=description,
        alarm_data=alarm_data_json,
        priority=priority,
        creator_id=None,  # 系统（数字孪生）创建
    )
    db.add(order)
    db.flush()

    create_msg = f"数字孪生系统下发（告警等级 {payload.alarmLevel}）"
    add_log(db, order, None, "CREATE", create_msg)

    # 派单：孪生端显式指派优先；否则 P1 时按设备负责人自动派单，无负责人则等待人工派发
    if assignee:
        order.assignee_id = assignee.id
        order.dispatch_time = datetime.now()
        order.status = models.WO_PENDING_ACCEPT
        add_log(db, order, None, "DISPATCH", f"孪生端指派 {assignee.real_name}")
    elif device.owner_id:
        owner = db.get(models.User, device.owner_id)
        if owner and owner.enabled and owner.role == models.ROLE_ENGINEER:
            order.assignee_id = owner.id
            order.dispatch_time = datetime.now()
            order.status = models.WO_PENDING_ACCEPT
            add_log(db, order, None, "DISPATCH", f"按设备负责人自动派单给 {owner.real_name}")

    db.commit()
    db.refresh(order)
    twin_log(db, "IN", "孪生下发工单",
             f"{order.order_no} {order.title}（等级{payload.alarmLevel}"
             + (f"，指派 {assignee.real_name}" if assignee else "，待派发") + "）")

    if order.assignee_id:
        notify_and_callback(
            db, order, "dispatched",
            target_ids={order.assignee_id},
            message=f"数字孪生紧急告警，新工单 {order.order_no}：{order.title}",
        )
    else:
        notify_and_callback(
            db, order, "created",
            target_roles=_MANAGERS,
            message=f"数字孪生紧急告警，新工单 {order.order_no} 待派发：{order.title}",
        )
    return {"kind": "work_order", "data": wo_to_dict(db, order)}


# ---------- 流转动作 ----------

@router.post("/{order_id}/dispatch")
def dispatch(
    order_id: int,
    payload: DispatchIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*_MANAGERS, module="orders")),
):
    order = _get_order(db, order_id)
    if order.status not in _ALLOWED["dispatch"]:
        raise HTTPException(400, "当前状态不可派单")
    assignee = db.get(models.User, payload.assignee_id)
    if assignee is None or assignee.role != models.ROLE_ENGINEER or not assignee.enabled:
        raise HTTPException(400, "指派的工程师不存在或不可用")

    order.assignee_id = assignee.id
    order.dispatcher_id = user.id
    order.dispatch_time = datetime.now()
    order.status = models.WO_PENDING_ACCEPT
    add_log(db, order, user, "DISPATCH", f"派单给 {assignee.real_name}")
    audit(db, user, "ORDER_DISPATCH", f"工单 {order.order_no} 派单给 {assignee.real_name}")
    db.commit()
    notify_and_callback(
        db, order, "dispatched",
        target_ids={assignee.id},
        message=f"收到新工单 {order.order_no}：{order.title}",
    )
    return wo_to_dict(db, order)


@router.post("/{order_id}/accept")
def accept(
    order_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("orders")),
):
    order = _get_order(db, order_id)
    if order.status not in _ALLOWED["accept"]:
        raise HTTPException(400, "当前状态不可接单")
    if order.assignee_id != user.id:
        raise HTTPException(403, "该工单未指派给你")
    order.accept_time = datetime.now()
    order.status = models.WO_PROCESSING
    add_log(db, order, user, "ACCEPT", "接单，开始处理")
    db.commit()
    notify_and_callback(
        db, order, "accepted",
        target_roles=_MANAGERS,
        message=f"{user.real_name} 已接单：{order.order_no}",
    )
    return wo_to_dict(db, order)


@router.post("/{order_id}/complete")
def complete(
    order_id: int,
    payload: CompleteIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("orders")),
):
    order = _get_order(db, order_id)
    if order.status not in _ALLOWED["complete"]:
        raise HTTPException(400, "当前状态不可提交完成")
    if order.assignee_id != user.id:
        raise HTTPException(403, "该工单未指派给你")
    order.finish_time = datetime.now()
    order.status = models.WO_PENDING_VERIFY
    add_log(db, order, user, "COMPLETE", payload.result or "已处理完毕，提交验收")

    # 绑定提交完成时上传的处理附件（仅限本人上传的草稿）
    if payload.draft_file_ids:
        drafts = db.query(models.FileRecord).filter(
            models.FileRecord.id.in_(payload.draft_file_ids),
            models.FileRecord.category == "DRAFT",
            models.FileRecord.uploader_id == user.id,
        ).all()
        for f in drafts:
            f.order_id = order.id
            f.category = "ORDER"
    db.commit()
    notify_and_callback(
        db, order, "completed",
        target_roles=_MANAGERS,
        message=f"工单 {order.order_no} 已提交验收",
    )
    return wo_to_dict(db, order)


@router.post("/{order_id}/verify")
def verify(
    order_id: int,
    payload: VerifyIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*_MANAGERS, module="orders")),
):
    order = _get_order(db, order_id)
    if order.status not in _ALLOWED["verify"]:
        raise HTTPException(400, "当前状态不可验收")
    if payload.passed:
        order.verify_time = datetime.now()
        order.status = models.WO_COMPLETED
        add_log(db, order, user, "VERIFY_PASS", payload.comment or "验收通过")
        audit(db, user, "ORDER_VERIFY", f"工单 {order.order_no} 验收通过：{payload.comment}")
        event, message = "verified", f"工单 {order.order_no} 已验收通过"
    else:
        order.status = models.WO_PROCESSING
        add_log(db, order, user, "VERIFY_REJECT", payload.comment or "验收不通过，退回处理")
        audit(db, user, "ORDER_VERIFY_REJECT", f"工单 {order.order_no} 验收驳回：{payload.comment}")
        event, message = "verify_rejected", f"工单 {order.order_no} 验收不通过，已退回处理"
    db.commit()
    notify_and_callback(
        db, order, event,
        target_ids={order.assignee_id} if order.assignee_id else set(),
        target_roles=_MANAGERS,
        message=message,
    )
    return wo_to_dict(db, order)


@router.post("/{order_id}/cancel")
def cancel(
    order_id: int,
    payload: CancelIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("orders")),
):
    order = _get_order(db, order_id)
    if order.status not in _ALLOWED["cancel"]:
        raise HTTPException(400, "当前状态不可取消")
    if user.role not in _MANAGERS and user.id != order.creator_id:
        raise HTTPException(403, "无权取消该工单")
    order.cancel_time = datetime.now()
    order.status = models.WO_CANCELLED
    add_log(db, order, user, "CANCEL", payload.reason or "取消工单")
    audit(db, user, "ORDER_CANCEL", f"工单 {order.order_no} 取消：{payload.reason}")
    db.commit()
    notify_and_callback(
        db, order, "cancelled",
        target_ids={order.assignee_id} if order.assignee_id else set(),
        target_roles=_MANAGERS,
        message=f"工单 {order.order_no} 已取消",
    )
    return wo_to_dict(db, order)
