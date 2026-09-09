"""工作台统计接口。"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import require_module
from ..services import wo_to_dict

router = APIRouter(prefix="/dashboard", tags=["工作台"])


@router.get("/summary")
def summary(
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("dashboard")),
):
    base = db.query(models.WorkOrder)
    if user.role == models.ROLE_ENGINEER:
        base = base.filter(models.WorkOrder.assignee_id == user.id)

    rows = (
        base.with_entities(models.WorkOrder.status, func.count(models.WorkOrder.id))
        .group_by(models.WorkOrder.status)
        .all()
    )
    status_counts = {status: count for status, count in rows}

    today = datetime.now().strftime("%Y-%m-%d")
    created_today = base.filter(models.WorkOrder.created_at >= today).count()
    month_start = datetime.now().strftime("%Y-%m-01")
    completed_month = base.filter(
        models.WorkOrder.status == models.WO_COMPLETED,
        models.WorkOrder.verify_time >= month_start,
    ).count()
    pending = sum(
        status_counts.get(s, 0)
        for s in (models.WO_PENDING_DISPATCH, models.WO_PENDING_ACCEPT, models.WO_PROCESSING, models.WO_PENDING_VERIFY)
    )

    # 平均处理时长（接单 → 提交完成），单位为小时
    durations = [
        (wo.finish_time - wo.accept_time).total_seconds() / 3600
        for wo in base.filter(
            models.WorkOrder.accept_time.isnot(None),
            models.WorkOrder.finish_time.isnot(None),
        ).all()
        if wo.finish_time and wo.accept_time
    ]
    avg_hours = round(sum(durations) / len(durations), 1) if durations else 0

    device_rows = (
        db.query(models.Device.status, func.count(models.Device.id))
        .group_by(models.Device.status)
        .all()
    )
    device_status = {
        models.DEVICE_STATUS.get(s, s): c for s, c in device_rows
    }

    recent = base.order_by(models.WorkOrder.id.desc()).limit(6).all()

    # 待审核报修单数量（工程师只统计自己提报的）
    rr_base = db.query(models.RepairRequest)
    if user.role == models.ROLE_ENGINEER:
        rr_base = rr_base.filter(models.RepairRequest.creator_id == user.id)
    pending_reviews = rr_base.filter(
        models.RepairRequest.status == models.RR_PENDING_REVIEW
    ).count()

    return {
        "status_counts": [
            {"status": s, "label": models.WO_STATUS_LABELS.get(s, s), "count": status_counts.get(s, 0)}
            for s in models.WO_STATUS_LABELS
        ],
        "created_today": created_today,
        "completed_month": completed_month,
        "pending": pending,
        "avg_hours": avg_hours,
        "pending_reviews": pending_reviews,
        "device_status": device_status,
        "recent": [wo_to_dict(db, wo) for wo in recent],
    }
