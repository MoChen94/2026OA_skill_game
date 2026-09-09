"""WebSocket 连接管理：按用户推送实时事件。

接口均为 async，由 FastAPI 主事件循环调用；同步接口需要推送时，
通过 push() 把协程调度回主事件循环执行。
"""
import asyncio
import json
from typing import Dict, Set

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._conns: Dict[int, Set[WebSocket]] = {}

    async def connect(self, user_id: int, ws: WebSocket) -> None:
        await ws.accept()
        self._conns.setdefault(user_id, set()).add(ws)

    async def disconnect(self, user_id: int, ws: WebSocket) -> None:
        conns = self._conns.get(user_id)
        if conns:
            conns.discard(ws)
            if not conns:
                self._conns.pop(user_id, None)

    async def send_to_users(self, user_ids, payload: dict) -> None:
        if not user_ids:
            return
        message = json.dumps(payload, ensure_ascii=False, default=str)
        targets = [ws for uid in user_ids for ws in list(self._conns.get(uid, ()))]
        for ws in targets:
            try:
                await ws.send_text(message)
            except Exception:
                # 连接已失效，找机会清理即可
                pass


manager = ConnectionManager()

_main_loop: asyncio.AbstractEventLoop | None = None


def capture_main_loop() -> None:
    """在 WebSocket 握手（主事件循环内）调用，记录主循环引用。"""
    global _main_loop
    try:
        _main_loop = asyncio.get_running_loop()
    except RuntimeError:
        pass


def push(user_ids, payload: dict) -> None:
    """同步接口中调用：把推送调度到主事件循环执行，不阻塞调用方。"""
    loop = _main_loop
    if loop is None or loop.is_closed() or not user_ids:
        return
    asyncio.run_coroutine_threadsafe(manager.send_to_users(list(user_ids), payload), loop)
