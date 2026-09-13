# -*- coding: utf-8 -*-
"""在线沟通路由：全员群，纯文字 + @提及，WebSocket 实时推送。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import require_module

router = APIRouter(prefix="/chat", tags=["在线沟通"])


class ChatMessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    mentions: list[int] = []  # 被@的用户ID列表


class ChatReadIn(BaseModel):
    last_read_msg_id: int


def _to_dict(msg: models.ChatMessage, me_id: int) -> dict:
    mention_ids = [int(x) for x in (msg.mentions or "").split(",") if x]
    return {
        "id": msg.id,
        "sender_id": msg.sender_id,
        "sender_name": msg.sender.real_name if msg.sender else "?",
        "content": msg.content,
        "mentions": mention_ids,
        "at_me": me_id in mention_ids,
        "created_at": msg.created_at.isoformat(timespec="minutes"),
    }


def _get_read(db: Session, user_id: int) -> int:
    row = db.get(models.ChatRead, user_id)
    return row.last_read_msg_id if row else 0


@router.get("/members")
def members(
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("chat")),
):
    """群成员列表（@下拉框用）。"""
    users = (
        db.query(models.User)
        .filter(models.User.enabled.is_(True))
        .order_by(models.User.id)
        .all()
    )
    return [
        {"id": u.id, "real_name": u.real_name, "title": u.title,
         "role": u.role, "online": False}
        for u in users if "chat" in u.modules or u.role == models.ROLE_ADMIN
    ]


@router.get("/messages")
def list_messages(
    after_id: int = Query(default=0, description="增量拉取：只返回 id 大于该值的消息"),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("chat")),
):
    """历史/增量消息：after_id=0 拉最近 limit 条；否则拉该 id 之后的。"""
    q = db.query(models.ChatMessage)
    if after_id > 0:
        msgs = (
            q.filter(models.ChatMessage.id > after_id)
            .order_by(models.ChatMessage.id.asc())
            .limit(limit)
            .all()
        )
    else:
        msgs = (
            q.order_by(models.ChatMessage.id.desc())
            .limit(limit)
            .all()
        )
        msgs.reverse()
    return {
        "items": [_to_dict(m, user.id) for m in msgs],
        "has_more": len(msgs) == limit and after_id == 0,
    }


@router.post("/messages")
def send_message(
    payload: ChatMessageIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("chat")),
):
    """发送消息（纯文字 + @提及），WebSocket 实时推送给全员。"""
    content = payload.content.strip()
    if not content:
        raise HTTPException(400, "消息内容不能为空")
    # @的必须是真实存在的用户，且名字确实出现在内容里（防伪造 @）
    valid_ids = []
    if payload.mentions:
        id_set = set(payload.mentions)
        users = db.query(models.User).filter(models.User.id.in_(id_set)).all()
        for u in users:
            if f"@{u.real_name}" in content:
                valid_ids.append(u.id)
    msg = models.ChatMessage(
        sender_id=user.id,
        content=content,
        mentions=",".join(str(i) for i in valid_ids),
    )
    db.add(msg)
    # 发送者自己立即视为已读
    row = db.get(models.ChatRead, user.id)
    if row is None:
        db.add(models.ChatRead(user_id=user.id, last_read_msg_id=0))
        db.flush()
        row = db.get(models.ChatRead, user.id)
    db.commit()
    db.refresh(msg)
    row.last_read_msg_id = msg.id
    db.commit()

    # WebSocket 推送给所有有 chat 权限的用户（在线者即时收到）
    from ..ws_manager import push
    targets = [
        u.id for u in db.query(models.User).filter(models.User.enabled.is_(True)).all()
        if u.role == models.ROLE_ADMIN or "chat" in u.modules
    ]
    data = _to_dict(msg, 0)
    push(targets, {
        "event": "chat",
        "message": f"{data['sender_name']}：{data['content'][:50]}",
        "chat": data,
    })
    return _to_dict(msg, user.id)


@router.get("/unread")
def unread(
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("chat")),
):
    """未读消息数（菜单红点用）。"""
    last_read = _get_read(db, user.id)
    count = (
        db.query(models.ChatMessage)
        .filter(models.ChatMessage.id > last_read)
        .count()
    )
    return {"unread": count, "last_read_msg_id": last_read}


@router.post("/read")
def mark_read(
    payload: ChatReadIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_module("chat")),
):
    """标记已读水位。"""
    row = db.get(models.ChatRead, user.id)
    if row is None:
        db.add(models.ChatRead(user_id=user.id, last_read_msg_id=payload.last_read_msg_id))
    else:
        row.last_read_msg_id = max(row.last_read_msg_id, payload.last_read_msg_id)
    db.commit()
    return {"ok": True}
