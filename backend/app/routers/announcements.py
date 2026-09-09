"""公告通知：发布 / 列表 / 详情(标记已读) / 未读数 / 删除。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import require_module, require_roles
from ..schemas import AnnouncementIn
from ..services import audit

router = APIRouter(prefix="/announcements", tags=["公告通知"])

_MANAGERS = (models.ROLE_ADMIN, models.ROLE_DISPATCHER)


def _to_dict(db: Session, a: models.Announcement, user: models.User) -> dict:
    read = (
        db.query(models.AnnouncementRead)
        .filter(
            models.AnnouncementRead.announcement_id == a.id,
            models.AnnouncementRead.user_id == user.id,
        )
        .first()
        is not None
    )
    return {
        "id": a.id,
        "title": a.title,
        "content": a.content,
        "is_top": a.is_top,
        "publisher_name": a.publisher.real_name if a.publisher else "系统",
        "created_at": a.created_at.isoformat(timespec="minutes"),
        "read": read,
    }


@router.get("")
def list_announcements(
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("announce")),
):
    items = (
        db.query(models.Announcement)
        .order_by(models.Announcement.is_top.desc(), models.Announcement.id.desc())
        .all()
    )
    return [_to_dict(db, a, user) for a in items]


@router.get("/unread-count")
def unread_count(
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("announce")),
):
    total = db.query(models.Announcement).count()
    read = (
        db.query(models.AnnouncementRead)
        .filter(models.AnnouncementRead.user_id == user.id)
        .count()
    )
    return {"unread": max(total - read, 0)}


@router.get("/{aid}")
def get_announcement(
    aid: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("announce")),
):
    a = db.get(models.Announcement, aid)
    if a is None:
        raise HTTPException(404, "公告不存在")
    exists = (
        db.query(models.AnnouncementRead)
        .filter(
            models.AnnouncementRead.announcement_id == aid,
            models.AnnouncementRead.user_id == user.id,
        )
        .first()
    )
    if exists is None:
        db.add(models.AnnouncementRead(announcement_id=aid, user_id=user.id))
        db.commit()
    return _to_dict(db, a, user)


@router.post("")
def publish(
    payload: AnnouncementIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*_MANAGERS, module="announce")),
):
    a = models.Announcement(
        title=payload.title, content=payload.content,
        publisher_id=user.id, is_top=payload.is_top,
    )
    db.add(a)
    audit(db, user, "ANNOUNCE_PUBLISH", f"发布公告《{payload.title}》")
    db.commit()
    db.refresh(a)
    return _to_dict(db, a, user)


@router.delete("/{aid}")
def delete_announcement(
    aid: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(models.ROLE_ADMIN, module="announce")),
):
    a = db.get(models.Announcement, aid)
    if a is None:
        raise HTTPException(404, "公告不存在")
    db.query(models.AnnouncementRead).filter(
        models.AnnouncementRead.announcement_id == aid
    ).delete()
    audit(db, user, "ANNOUNCE_DELETE", f"删除公告《{a.title}》")
    db.delete(a)
    db.commit()
    return {"ok": True}
