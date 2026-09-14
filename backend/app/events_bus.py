"""跨请求事件总线：工单变化时唤醒所有长轮询等待者。

实现用 threading.Condition（同步友好）：
- 变更方（同步路由线程）调用 bus.ping()
- 长轮询端点（同步 def，跑在线程池）用 bus.wait(version, timeout) 挂起等待
"""
import threading
import time


class EventBus:
    def __init__(self) -> None:
        self._cond = threading.Condition()
        self.version = 0

    def ping(self) -> None:
        """任何工单相关变化后调用：唤醒所有等待者。"""
        with self._cond:
            self.version += 1
            self._cond.notify_all()

    def wait(self, seen_version: int, timeout: float) -> int:
        """挂起等待直到 version 变化或超时，返回当前 version。"""
        deadline = time.monotonic() + max(timeout, 0)
        with self._cond:
            if self.version != seen_version:
                return self.version
            remaining = deadline - time.monotonic()
            if remaining > 0:
                self._cond.wait(remaining)
            return self.version


bus = EventBus()
