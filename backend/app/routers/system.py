"""审计日志与系统运维接口。"""
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import config, models
from ..database import get_db
from ..deps import require_roles

router = APIRouter(tags=["审计与系统"])


@router.get("/audit-logs")
def list_audit_logs(
    action: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(models.ROLE_ADMIN)),
):
    q = db.query(models.AuditLog)
    if action:
        q = q.filter(models.AuditLog.action == action)
    total = q.count()
    items = (
        q.order_by(models.AuditLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total": total,
        "items": [
            {
                "id": log.id,
                "username": log.username,
                "action": log.action,
                "detail": log.detail,
                "ip": log.ip,
                "created_at": log.created_at.isoformat(timespec="seconds"),
            }
            for log in items
        ],
    }


def backup_database() -> str | None:
    """复制数据库文件到 backups 目录，保留最近 7 份。返回备份文件名。"""
    src = Path(config.DB_PATH)
    if not src.exists():
        return None
    dst_dir = Path(config.DATA_DIR) / "backups"
    dst_dir.mkdir(parents=True, exist_ok=True)
    name = f"oatool-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    shutil.copy2(src, dst_dir / name)
    backups = sorted(dst_dir.glob("oatool-*.db"))
    for f in backups[:-7]:
        f.unlink()
    return name


@router.post("/system/backup-now")
def backup_now(
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(models.ROLE_ADMIN)),
):
    name = backup_database()
    if name is None:
        return {"ok": False, "detail": "数据库文件不存在"}
    return {"ok": True, "file": name, "dir": str(Path(config.DATA_DIR) / "backups")}
