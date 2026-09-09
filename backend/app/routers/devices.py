"""设备台账接口。"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .. import config, models
from ..database import get_db
from ..deps import require_module, require_roles
from ..schemas import DeviceIn, DeviceStatusSyncIn
from ..services import audit, notify_users, twin_log

router = APIRouter(prefix="/devices", tags=["设备台账"])


def warranty_info(d: models.Device) -> dict:
    """保修状态：在保 / 临近到期(30 天内) / 已过保（按月×30 天近似计算）。"""
    if not d.purchase_date or not d.warranty_months:
        return {"status": None, "status_label": "—", "expire": None}
    expire = d.purchase_date + timedelta(days=d.warranty_months * 30)
    days_left = (expire - datetime.now()).days
    expire_str = expire.strftime("%Y-%m-%d")
    if days_left < 0:
        return {"status": "expired", "status_label": "已过保", "expire": expire_str}
    if days_left <= 30:
        return {"status": "expiring", "status_label": "临近到期", "expire": expire_str}
    return {"status": "active", "status_label": "在保", "expire": expire_str}


def device_to_dict(d: models.Device) -> dict:
    return {
        "id": d.id,
        "code": d.code,
        "name": d.name,
        "location": d.location,
        "twin_id": d.twin_id,
        "status": d.status,
        "status_label": models.DEVICE_STATUS.get(d.status, d.status),
        "owner_id": d.owner_id,
        "owner_name": d.owner.real_name if d.owner else None,
        "description": d.description,
        "model": d.model,
        "manufacturer": d.manufacturer,
        "purchase_date": d.purchase_date.strftime("%Y-%m-%d") if d.purchase_date else None,
        "warranty_months": d.warranty_months,
        "warranty": warranty_info(d),
    }


@router.delete("/all")
def clear_all_devices(
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(models.ROLE_ADMIN)),
):
    """清空全部设备台账（连带保养计划），仅管理员。需先清空全部工单。"""
    linked = db.query(models.WorkOrder).filter(models.WorkOrder.device_id.isnot(None)).count()
    linked_rr = db.query(models.RepairRequest).filter(models.RepairRequest.device_id.isnot(None)).count()
    if linked or linked_rr:
        raise HTTPException(400, f"仍有 {linked} 张工单 / {linked_rr} 张报修单关联设备，请先在工单管理中清空全部工单")
    n_plans = db.query(models.MaintenancePlan).count()
    db.query(models.MaintenancePlan).delete()
    n = db.query(models.Device).count()
    db.query(models.Device).delete()
    audit(db, user, "DEVICE_CLEAR_ALL", f"清空全部设备（{n} 台，保养计划 {n_plans} 个）")
    db.commit()
    return {"ok": True, "deleted": n, "deleted_plans": n_plans}


@router.post("/sync-status")
def sync_status(
    payload: DeviceStatusSyncIn,
    db: Session = Depends(get_db),
    x_api_key: str | None = Header(default=None),
):
    """数字孪生系统推送设备实时状态。白名单模式：局域网内直接调用，无需鉴权。"""
    if payload.status not in models.DEVICE_STATUS:
        raise HTTPException(400, "设备状态不合法")
    device = db.query(models.Device).filter(models.Device.code == payload.deviceCode).first()
    if device is None:
        raise HTTPException(404, f"设备编号 {payload.deviceCode} 未在设备台账中登记")
    old = device.status
    device.status = payload.status
    audit(db, None, "TWIN_SYNC",
          f"孪生同步设备 {device.code} 状态 {old} → {payload.status}", "")
    db.commit()
    twin_log(db, "IN", "设备状态同步", f"{device.code} {device.name}：{old} → {payload.status}")
    if old != payload.status:
        notify_users(
            db, "device_status_changed",
            f"设备 {device.code} {device.name} 状态变更为 {models.DEVICE_STATUS.get(payload.status, payload.status)}",
            target_roles=(models.ROLE_ADMIN, models.ROLE_DISPATCHER),
            extra={"deviceCode": device.code, "status": payload.status},
        )
    return {"ok": True, "deviceCode": device.code, "status": payload.status,
            "status_label": models.DEVICE_STATUS.get(payload.status, payload.status)}


@router.get("")
def list_devices(
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("devices")),
):
    return [device_to_dict(d) for d in db.query(models.Device).order_by(models.Device.code).all()]


@router.post("")
def create_device(
    payload: DeviceIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(models.ROLE_ADMIN, models.ROLE_DISPATCHER, module="devices")),
):
    if db.query(models.Device).filter(models.Device.code == payload.code).first():
        raise HTTPException(400, f"设备编号 {payload.code} 已存在")
    device = models.Device(**payload.model_dump())
    db.add(device)
    audit(db, user, "DEVICE_CREATE", f"新增设备 {payload.code} {payload.name}")
    db.commit()
    return device_to_dict(device)


@router.put("/{device_id}")
def update_device(
    device_id: int,
    payload: DeviceIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(models.ROLE_ADMIN, models.ROLE_DISPATCHER, module="devices")),
):
    device = db.get(models.Device, device_id)
    if device is None:
        raise HTTPException(404, "设备不存在")
    dup = (
        db.query(models.Device)
        .filter(models.Device.code == payload.code, models.Device.id != device_id)
        .first()
    )
    if dup:
        raise HTTPException(400, f"设备编号 {payload.code} 已存在")
    for key, value in payload.model_dump().items():
        setattr(device, key, value)
    audit(db, user, "DEVICE_UPDATE", f"修改设备 {payload.code}")
    db.commit()
    return device_to_dict(device)


@router.delete("/{device_id}")
def delete_device(
    device_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(models.ROLE_ADMIN, module="devices")),
):
    device = db.get(models.Device, device_id)
    if device is None:
        raise HTTPException(404, "设备不存在")
    in_use = db.query(models.WorkOrder).filter(models.WorkOrder.device_id == device_id).count()
    if in_use:
        raise HTTPException(400, "该设备存在关联工单，不能删除")
    audit(db, user, "DEVICE_DELETE", f"删除设备 {device.code} {device.name}")
    db.delete(device)
    db.commit()
    return {"ok": True}
