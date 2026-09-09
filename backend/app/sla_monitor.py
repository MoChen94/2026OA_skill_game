"""后台任务：保养计划到期扫描 + 每日数据备份。

- 保养：到期计划自动生成保养工单。
- 备份：每天 03:00 后备份一次数据库（保留 7 份）。
"""
import asyncio
from datetime import datetime

from .database import SessionLocal
from .routers.maintenance import scan_due_plans

SCAN_INTERVAL_SECONDS = 60
FIRST_SCAN_DELAY_SECONDS = 5  # 启动后先扫一次，便于演示


async def background_loop() -> None:
    await asyncio.sleep(FIRST_SCAN_DELAY_SECONDS)
    while True:
        try:
            db = SessionLocal()
            try:
                scan_due_plans(db)
            finally:
                db.close()
        except Exception:
            pass
        try:
            _daily_backup()
        except Exception:
            pass
        await asyncio.sleep(SCAN_INTERVAL_SECONDS)


_last_backup_date: str | None = None


def _daily_backup() -> None:
    """每天 03:00 后备份一次数据库到 data/backups，保留最近 7 份。"""
    global _last_backup_date
    from .routers.system import backup_database

    now = datetime.now()
    today = now.strftime("%Y%m%d")
    if now.hour < 3 or _last_backup_date == today:
        return
    name = backup_database()
    if name:
        _last_backup_date = today
        print(f"[backup] 每日数据库备份完成：{name}")
