"""OA 服务启动器（Windows 断网防崩版）。

背景：Python 在 Windows 的 Proactor(IOCP) 事件循环存在缺陷——客户端在
accept 瞬间突兀断开（断网时所有连接同时重置）会抛
"OSError [WinError 64] 指定的网络名不再可用"，事件循环未捕获该异常，
整个服务进程直接退出。uvicorn 在 Windows 上默认使用 Proactor 循环。

修复：切换为 Selector 事件循环（对该类 accept 错误免疫），局域网规模
（百级并发以内）性能无差异。

用法：python run.py [端口]   （默认 8001）
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

if sys.platform == "win32":
    # 双保险：策略 + 直接替换 uvicorn 的循环工厂为 Selector
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        import uvicorn.loops.asyncio as _ua

        _ua.asyncio_loop_factory = lambda use_subprocess=False: asyncio.SelectorEventLoop
    except Exception:
        pass

import uvicorn  # noqa: E402

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8001

uvicorn.run(
    "app.main:app",
    host="0.0.0.0",
    port=PORT,
    loop="none",  # 使用当前策略（已设为 Selector），不强制 Proactor
)
