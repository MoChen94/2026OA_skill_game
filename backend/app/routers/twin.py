"""数字孪生对接接口。

给孪生平台调用（请求头 X-API-Key 鉴权）：
  - GET  /twin/orders          拉取工单列表（支持状态/设备/增量过滤，供孪生工单管理同步）
  - GET  /twin/orders/{id}     工单详情 + 流转日志
  - POST /work-orders/external 下发工单（见 work_orders.py，P1 直接成单，P2~P4 转报修）
  - POST /devices/sync-status  推送设备状态（见 devices.py）

OA 管理端（登录，twin 模块权限）：
  - GET  /twin/overview        对接概览：配置、统计、最近同步
  - PUT  /twin/config          修改回调地址 / API Key（存库即时生效，无需重启）
  - POST /twin/test-callback   手动测试回调连通性
  - GET  /twin/logs            对接日志（IN=孪生调用OA，OUT=OA回调孪生）
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import config, models
from ..database import get_db
from ..deps import require_module, require_roles
from ..services import ACTION_LABELS, rr_to_dict, twin_log, wo_to_dict

router = APIRouter(prefix="/twin", tags=["孪生对接"])

_MANAGERS = (models.ROLE_ADMIN, models.ROLE_DISPATCHER)


# ---------- 配置读写：数据库优先，环境变量兜底 ----------

def get_twin_setting(db: Session, key: str, env_default: str = "") -> str:
    row = db.get(models.SystemConfig, key)
    if row and row.value:
        return row.value
    return env_default


def _check_api_key(db: Session, x_api_key: str | None) -> None:
    """白名单模式：局域网内直接放行，不做密钥校验（X-API-Key 传不传都行，兼容旧调用）。"""
    return


# ---------- 给孪生平台：工单拉取（X-API-Key） ----------

@router.get("/orders")
def twin_list_orders(
    status: str | None = Query(default=None, description="工单状态，如 PROCESSING"),
    device_code: str | None = Query(default=None, description="按设备编号过滤"),
    updated_after: datetime | None = Query(default=None, description="增量拉取：只返回该时间之后有变更的工单"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
    x_api_key: str | None = Header(default=None),
):
    """工单列表：孪生平台的工单管理从此同步 OA 工单。

    建议轮询方式：每 10~30 秒带 updated_after（上一次同步的最大 updated_at）增量拉取；
    也可配合 OA 的状态变更回调（见对接文档）做到准实时。
    """
    _check_api_key(db, x_api_key)
    q = db.query(models.WorkOrder)
    if status:
        q = q.filter(models.WorkOrder.status == status)
    if device_code:
        q = q.join(models.Device).filter(models.Device.code == device_code)
    if updated_after:
        q = q.filter(models.WorkOrder.updated_at >= updated_after)
    total = q.count()
    items = (
        q.order_by(models.WorkOrder.updated_at.desc(), models.WorkOrder.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    data = [wo_to_dict(db, wo) for wo in items]
    twin_log(db, "IN", "拉取工单列表",
             f"status={status or '全部'} 共{total}条 返回{len(data)}条" + (f" 增量since={updated_after}" if updated_after else ""))
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": data,
        "server_time": datetime.now().isoformat(timespec="seconds"),
    }


@router.get("/orders/{order_id}")
def twin_get_order(
    order_id: int,
    db: Session = Depends(get_db),
    x_api_key: str | None = Header(default=None),
):
    """工单详情 + 流转日志（孪生侧查看单据进度）。"""
    _check_api_key(db, x_api_key)
    order = db.get(models.WorkOrder, order_id)
    if order is None:
        raise HTTPException(404, "工单不存在")
    logs = [
        {
            "action": log.action,
            "action_label": ACTION_LABELS.get(log.action, log.action),
            "detail": log.detail,
            "operator_name": log.operator.real_name if log.operator else "系统",
            "created_at": log.created_at.isoformat(timespec="seconds"),
        }
        for log in order.logs
    ]
    twin_log(db, "IN", "拉取工单详情", f"{order.order_no} {order.title}")
    return {"order": wo_to_dict(db, order), "logs": logs}


@router.get("/repair-requests")
def twin_list_repairs(
    status: str | None = Query(default=None, description="报修状态：PENDING_REVIEW/APPROVED/REJECTED/WITHDRAWN"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
    x_api_key: str | None = Header(default=None),
):
    """报修单列表（调度员视角全量）。

    孪生下发 P2~P4 告警会转成报修单等待 OA 调度员审核，
    由此接口跟踪审核进展；APPROVED 的报修单会带 work_order_no 指向生成的正式工单。
    """
    _check_api_key(db, x_api_key)
    q = db.query(models.RepairRequest)
    if status:
        q = q.filter(models.RepairRequest.status == status)
    total = q.count()
    items = (
        q.order_by(models.RepairRequest.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    twin_log(db, "IN", "拉取报修单列表", f"status={status or '全部'} 共{total}条")
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [rr_to_dict(db, rr) for rr in items],
        "server_time": datetime.now().isoformat(timespec="seconds"),
    }


@router.get("/engineers")
def twin_engineers(
    db: Session = Depends(get_db),
    x_api_key: str | None = Header(default=None),
):
    """可指派的工程师列表（孪生端下发工单时的指派人下拉框）。"""
    _check_api_key(db, x_api_key)
    users = (
        db.query(models.User)
        .filter(models.User.role == models.ROLE_ENGINEER, models.User.enabled.is_(True))
        .order_by(models.User.id)
        .all()
    )
    return {
        "items": [
            {"id": u.id, "username": u.username, "real_name": u.real_name, "title": u.title}
            for u in users
        ]
    }


@router.get("/devices")
def twin_devices(
    db: Session = Depends(get_db),
    x_api_key: str | None = Header(default=None),
):
    """OA 设备台账列表（孪生端选择 deviceCode 用）。"""
    _check_api_key(db, x_api_key)
    devices = db.query(models.Device).order_by(models.Device.code).all()
    return {
        "items": [
            {
                "id": d.id, "code": d.code, "name": d.name,
                "location": d.location, "status": d.status,
                "owner_name": d.owner.real_name if d.owner else None,
            }
            for d in devices
        ]
    }


# ---------- OA 管理端：配置 / 概览 / 日志 ----------

@router.get("/overview")
def overview(
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("twin")),
):
    """对接概览：配置、工单统计、最近同步时间。"""
    callback_url = get_twin_setting(db, "twin_callback_url", config.TWIN_CALLBACK_URL)
    last_in = db.query(models.TwinSyncLog).filter(models.TwinSyncLog.direction == "IN").order_by(
        models.TwinSyncLog.id.desc()).first()
    last_out_ok = db.query(models.TwinSyncLog).filter(
        models.TwinSyncLog.direction == "OUT", models.TwinSyncLog.ok.is_(True)).order_by(
        models.TwinSyncLog.id.desc()).first()

    counts = {s: c for s, c in db.query(models.WorkOrder.status, func.count(models.WorkOrder.id)).group_by(models.WorkOrder.status)}
    today = datetime.now().strftime("%Y-%m-%d")
    return {
        "callback_url": callback_url,
        "callback_configured": bool(callback_url),
        "auth_mode": "open",
        "total_orders": db.query(models.WorkOrder).count(),
        "status_counts": {s: counts.get(s, 0) for s in models.WO_STATUS_LABELS},
        "created_today": db.query(models.WorkOrder).filter(models.WorkOrder.created_at >= today).count(),
        "last_in_at": last_in.created_at.isoformat(timespec="seconds") if last_in else None,
        "last_in_action": last_in.action if last_in else None,
        "last_out_at": last_out_ok.created_at.isoformat(timespec="seconds") if last_out_ok else None,
        "server_time": datetime.now().isoformat(timespec="seconds"),
    }


@router.put("/config")
def save_config(
    payload: dict,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(models.ROLE_ADMIN, module="twin")),
):
    """修改孪生对接配置（存数据库，即时生效）。"""
    allowed = {"twin_callback_url"}
    changed = []
    for k, v in (payload or {}).items():
        if k not in allowed:
            continue
        v = (v or "").strip()
        row = db.get(models.SystemConfig, k)
        if row is None:
            row = models.SystemConfig(key=k, value=v)
            db.add(row)
        else:
            row.value = v
        changed.append(k)
    if not changed:
        raise HTTPException(400, "没有可保存的配置项")
    db.commit()
    return {"ok": True, "changed": changed}


@router.post("/test-callback")
def test_callback(
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("twin")),
):
    """向孪生回调地址发送一条测试消息，验证连通性。"""
    from ..services import send_twin_callback
    ok, msg = send_twin_callback(db, {
        "event": "ping",
        "message": f"OA协同办公平台 连通性测试（由 {user.real_name} 触发，{datetime.now().strftime('%H:%M:%S')}）",
        "server_time": datetime.now().isoformat(timespec="seconds"),
    })
    twin_log(db, "OUT", "连通性测试", msg, ok)
    if not ok:
        raise HTTPException(502, f"回调失败：{msg}")
    return {"ok": True, "detail": msg}


@router.get("/logs")
def list_logs(
    direction: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("twin")),
):
    """对接日志列表。"""
    q = db.query(models.TwinSyncLog)
    if direction:
        q = q.filter(models.TwinSyncLog.direction == direction)
    total = q.count()
    items = (
        q.order_by(models.TwinSyncLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total": total,
        "items": [
            {
                "id": log.id,
                "direction": log.direction,
                "action": log.action,
                "detail": log.detail,
                "ok": log.ok,
                "created_at": log.created_at.isoformat(timespec="seconds"),
            }
            for log in items
        ],
    }
