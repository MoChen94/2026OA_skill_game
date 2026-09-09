"""WebSocket 实时推送端点：?token=<登录令牌>。"""
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..security import decode_token
from ..ws_manager import capture_main_loop, manager

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(default=""),
    db: Session = Depends(get_db),
):
    capture_main_loop()
    payload = decode_token(token) if token else None
    if not payload:
        await websocket.close(code=4401)
        return
    user = db.get(models.User, int(payload["sub"]))
    if user is None or not user.enabled:
        await websocket.close(code=4401)
        return

    await manager.connect(user.id, websocket)
    try:
        while True:
            await websocket.receive_text()  # 客户端心跳/任意消息；断线时抛出异常
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(user.id, websocket)
