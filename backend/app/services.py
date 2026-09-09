"""工单业务服务：编号生成、流转日志、实时推送、数字孪生回调。"""
import json
import threading
import urllib.request
from datetime import datetime

from sqlalchemy.orm import Session

from . import config, models
from .ws_manager import push


def gen_order_no(db: Session) -> str:
    date = datetime.now().strftime("%Y%m%d")
    prefix = f"WO{date}-"
    count = (
        db.query(models.WorkOrder)
        .filter(models.WorkOrder.order_no.like(f"{prefix}%"))
        .count()
    )
    return f"{prefix}{count + 1:03d}"


def gen_request_no(db: Session) -> str:
    date = datetime.now().strftime("%Y%m%d")
    prefix = f"BX{date}-"
    count = (
        db.query(models.RepairRequest)
        .filter(models.RepairRequest.request_no.like(f"{prefix}%"))
        .count()
    )
    return f"{prefix}{count + 1:03d}"


def notify_users(
    db: Session,
    event: str,
    message: str,
    target_ids: set[int] | None = None,
    target_roles: tuple[str, ...] = (),
    extra: dict | None = None,
) -> None:
    """仅 WebSocket 推送（不含孪生回调），用于报修单等非工单事件。"""
    payload = {
        "event": event,
        "message": message,
        "time": datetime.now().isoformat(timespec="seconds"),
    }
    if extra:
        payload.update(extra)
    ids = set(target_ids or ())
    if target_roles:
        ids |= {
            u.id
            for u in db.query(models.User)
            .filter(models.User.role.in_(target_roles), models.User.enabled.is_(True))
            .all()
        }
    if ids:
        push(ids, payload)


def add_log(db: Session, order: models.WorkOrder, operator: models.User | None, action: str, detail: str = "") -> None:
    db.add(
        models.WorkOrderLog(
            order_id=order.id,
            operator_id=operator.id if operator else None,
            action=action,
            detail=detail,
        )
    )


# 未完结状态（用于保养计划判断是否存在进行中的工单）
ACTIVE_STATUSES = (
    models.WO_PENDING_DISPATCH,
    models.WO_PENDING_ACCEPT,
    models.WO_PROCESSING,
    models.WO_PENDING_VERIFY,
)


ACTION_LABELS = {
    "CREATE": "创建工单",
    "DISPATCH": "派单",
    "ACCEPT": "接单",
    "COMPLETE": "提交完成",
    "VERIFY_PASS": "验收通过",
    "VERIFY_REJECT": "验收驳回",
    "CANCEL": "取消工单",
}


def notify_and_callback(
    db: Session,
    order: models.WorkOrder,
    event: str,
    target_ids: set[int] | None = None,
    target_roles: tuple[str, ...] = (),
    message: str = "",
) -> None:
    """WebSocket 实时推送 + 数字孪生状态回调。"""
    payload = {
        "event": event,
        "workOrderId": order.id,
        "orderNo": order.order_no,
        "title": order.title,
        "status": order.status,
        "message": message,
        "time": datetime.now().isoformat(timespec="seconds"),
    }
    ids = set(target_ids or ())
    if target_roles:
        ids |= {
            u.id
            for u in db.query(models.User)
            .filter(models.User.role.in_(target_roles), models.User.enabled.is_(True))
            .all()
        }
    if ids:
        push(ids, payload)

    twin_callback(db, order, event)


def twin_callback(db: Session, order: models.WorkOrder, event: str) -> None:
    """工单状态变更后回调数字孪生系统（配置了地址才回调，失败静默记录日志）。"""
    data = json.dumps(
        {
            "event": event,
            "orderId": order.id,
            "orderNo": order.order_no,
            "title": order.title,
            "deviceCode": order.device.code if order.device else None,
            "priority": order.priority,
            "status": order.status,
            "assignee": order.assignee.real_name if order.assignee else None,
            "acted_at": datetime.now().isoformat(timespec="seconds"),
        },
        ensure_ascii=False,
    ).encode("utf-8")

    def _post() -> None:
        from .database import SessionLocal
        from .routers.twin import get_twin_setting
        sess = SessionLocal()
        try:
            url = get_twin_setting(sess, "twin_callback_url", config.TWIN_CALLBACK_URL)
            if not url:
                return
            try:
                req = urllib.request.Request(
                    url, data=data, headers={"Content-Type": "application/json"}
                )
                urllib.request.urlopen(req, timeout=3)
                sess.add(models.TwinSyncLog(direction="OUT", action=f"回调·{event}",
                                            detail=f"{order.order_no} → {url}", ok=True))
            except Exception as e:
                sess.add(models.TwinSyncLog(direction="OUT", action=f"回调·{event}",
                                            detail=f"{order.order_no} 失败：{e}", ok=False))
            sess.commit()
        finally:
            sess.close()

    threading.Thread(target=_post, daemon=True).start()


def send_twin_callback(db: Session, payload: dict) -> tuple[bool, str]:
    """同步发送一条消息给孪生（连通性测试用）。返回 (是否成功, 说明)。"""
    from .routers.twin import get_twin_setting
    url = get_twin_setting(db, "twin_callback_url", config.TWIN_CALLBACK_URL)
    if not url:
        return False, "未配置回调地址（TWIN_CALLBACK_URL）"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=4)
        return True, f"已发送到 {url}"
    except Exception as e:
        return False, f"{url} 不可达：{e}"


def wo_to_dict(db: Session, wo: models.WorkOrder) -> dict:
    """工单 → 前端展示结构（带关联字段的中文展示值）。"""
    device = wo.device
    return {
        "id": wo.id,
        "order_no": wo.order_no,
        "title": wo.title,
        "order_type": wo.order_type,
        "order_type_label": models.WO_TYPES.get(wo.order_type, wo.order_type),
        "priority": wo.priority,
        "priority_label": models.WO_PRIORITIES.get(wo.priority, wo.priority),
        "status": wo.status,
        "status_label": models.WO_STATUS_LABELS.get(wo.status, wo.status),
        "device_id": wo.device_id,
        "device_code": device.code if device else None,
        "device_name": device.name if device else None,
        "device_location": device.location if device else None,
        "description": wo.description,
        "alarm_data": wo.alarm_data,
        "creator_id": wo.creator_id,
        "creator_name": wo.creator.real_name if wo.creator else "系统",
        "dispatcher_name": wo.dispatcher.real_name if wo.dispatcher else None,
        "assignee_id": wo.assignee_id,
        "assignee_name": wo.assignee.real_name if wo.assignee else None,
        "dispatch_time": wo.dispatch_time.isoformat(timespec="minutes") if wo.dispatch_time else None,
        "accept_time": wo.accept_time.isoformat(timespec="minutes") if wo.accept_time else None,
        "finish_time": wo.finish_time.isoformat(timespec="minutes") if wo.finish_time else None,
        "verify_time": wo.verify_time.isoformat(timespec="minutes") if wo.verify_time else None,
        "cancel_time": wo.cancel_time.isoformat(timespec="minutes") if wo.cancel_time else None,
        "created_at": wo.created_at.isoformat(timespec="minutes"),
        "updated_at": wo.updated_at.isoformat(timespec="seconds") if wo.updated_at else None,
    }


def rr_to_dict(db: Session, rr: models.RepairRequest) -> dict:
    device = rr.device
    return {
        "id": rr.id,
        "request_no": rr.request_no,
        "title": rr.title,
        "device_id": rr.device_id,
        "device_code": device.code if device else None,
        "device_name": device.name if device else None,
        "description": rr.description,
        "alarm_data": rr.alarm_data,
        "priority": rr.priority,
        "priority_label": models.WO_PRIORITIES.get(rr.priority, rr.priority),
        "status": rr.status,
        "status_label": models.RR_STATUS_LABELS.get(rr.status, rr.status),
        "creator_id": rr.creator_id,
        "creator_name": rr.creator.real_name if rr.creator else "系统",
        "reviewer_name": rr.reviewer.real_name if rr.reviewer else None,
        "review_comment": rr.review_comment,
        "review_time": rr.review_time.isoformat(timespec="minutes") if rr.review_time else None,
        "work_order_id": rr.work_order_id,
        "work_order_no": rr.work_order.order_no if rr.work_order else None,
        "created_at": rr.created_at.isoformat(timespec="minutes"),
    }


def audit(db: Session, user: models.User | None, action: str, detail: str = "", ip: str = "") -> None:
    """写入操作审计日志。"""
    db.add(
        models.AuditLog(
            user_id=user.id if user else None,
            username=user.real_name if user else "系统",
            action=action,
            detail=detail,
            ip=ip,
        )
    )


def twin_log(db: Session, direction: str, action: str, detail: str = "", ok: bool = True) -> None:
    """写入数字孪生对接日志：IN=孪生调用OA，OUT=OA回调孪生。"""
    db.add(models.TwinSyncLog(direction=direction, action=action, detail=detail[:500], ok=ok))
    db.commit()


def user_to_dict(user: models.User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "real_name": user.real_name,
        "role": user.role,
        "role_label": models.ROLE_LABELS.get(user.role, user.role),
        "title": user.title,
        "phone": user.phone,
        "dept_id": user.dept_id,
        "dept_name": user.department.name if user.department else None,
        "enabled": user.enabled,
        "permissions": user.modules,
    }
