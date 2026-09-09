"""工业大屏接口：全局视角数据（仅调度员/管理员）。"""
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import require_roles
from ..services import ACTIVE_STATUSES, rr_to_dict, wo_to_dict

router = APIRouter(prefix="/screen", tags=["工业大屏"])

_MANAGERS = (models.ROLE_ADMIN, models.ROLE_DISPATCHER)


@router.get("/summary")
def screen_summary(
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*_MANAGERS)),
):
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    orders = db.query(models.WorkOrder).all()
    created_today = sum(1 for o in orders if o.created_at.strftime("%Y-%m-%d") == today)
    completed_today = sum(
        1 for o in orders
        if o.status == models.WO_COMPLETED and o.verify_time and o.verify_time.strftime("%Y-%m-%d") == today
    )
    active = [o for o in orders if o.status in ACTIVE_STATUSES]

    status_counts = {
        s: sum(1 for o in orders if o.status == s) for s in models.WO_STATUS_LABELS
    }
    device_rows = (
        db.query(models.Device.status, func.count(models.Device.id))
        .group_by(models.Device.status)
        .all()
    )
    device_status = {models.DEVICE_STATUS.get(s, s): c for s, c in device_rows}
    device_total = sum(device_status.values())

    # 近 7 天趋势
    created_by_day: dict = defaultdict(int)
    done_by_day: dict = defaultdict(int)
    cutoff = now - timedelta(days=6)
    for o in orders:
        if o.created_at >= cutoff:
            created_by_day[o.created_at.strftime("%m-%d")] += 1
            if o.status == models.WO_COMPLETED and o.verify_time and o.verify_time >= cutoff:
                done_by_day[o.verify_time.strftime("%m-%d")] += 1
    labels = [(now - timedelta(days=i)).strftime("%m-%d") for i in range(6, -1, -1)]

    # 工程师 7 天完成排行
    eng_done: dict = defaultdict(int)
    eng_names: dict = {}
    for o in orders:
        if o.assignee_id and o.status == models.WO_COMPLETED and o.verify_time and o.verify_time >= cutoff:
            eng_done[o.assignee_id] += 1
            eng_names[o.assignee_id] = o.assignee.real_name if o.assignee else "?"
    ranking = sorted(
        ({"name": eng_names[uid], "value": c} for uid, c in eng_done.items()),
        key=lambda x: -x["value"],
    )[:8]

    recent_orders = sorted(orders, key=lambda o: o.created_at, reverse=True)[:10]
    pending_reviews = db.query(models.RepairRequest).filter(
        models.RepairRequest.status == models.RR_PENDING_REVIEW
    ).count()
    recent_repairs = (
        db.query(models.RepairRequest).order_by(models.RepairRequest.id.desc()).limit(6).all()
    )

    completed_30d = [
        o for o in orders
        if o.status == models.WO_COMPLETED and o.accept_time and o.finish_time
        and o.finish_time >= cutoff
    ]
    durations = [(o.finish_time - o.accept_time).total_seconds() / 3600 for o in completed_30d]
    avg_hours = round(sum(durations) / len(durations), 1) if durations else 0

    return {
        "device_total": device_total,
        "device_status": device_status,
        "created_today": created_today,
        "active_count": len(active),
        "completed_today": completed_today,
        "completion_rate_today": round(completed_today / created_today * 100, 1) if created_today else 0,
        "avg_hours": avg_hours,
        "pending_reviews": pending_reviews,
        "status_counts": [
            {"name": models.WO_STATUS_LABELS[s], "value": c} for s, c in status_counts.items()
        ],
        "trend": {
            "labels": labels,
            "created": [created_by_day.get(l, 0) for l in labels],
            "completed": [done_by_day.get(l, 0) for l in labels],
        },
        "engineer_ranking": ranking,
        "recent_orders": [wo_to_dict(db, o) for o in recent_orders],
        "recent_repairs": [rr_to_dict(db, r) for r in recent_repairs],
    }
