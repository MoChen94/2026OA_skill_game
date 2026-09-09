"""OA协同办公平台 - FastAPI 入口。

启动：python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
接口文档：http://<服务器IP>:8000/docs
"""
import asyncio
import time
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .routers import (
    announcements,
    approvals,
    auth,
    dashboard,
    devices,
    files,
    maintenance,
    repair_requests,
    reports,
    screen,
    system,
    twin,
    users,
    work_orders,
    ws,
)
from .seed import ensure_seed
from .sla_monitor import background_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_seed()
    monitor = asyncio.create_task(background_loop())
    yield
    monitor.cancel()


app = FastAPI(
    title="OA协同办公平台",
    description="光伏清洁企业局域网协同办公系统：工单调度、报修审批、设备台账、文件共享",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def no_cache_frontend(request, call_next):
    """前端可编辑文件（HTML/JS/CSS）禁用缓存，修改后刷新即生效；vendor 静态库保持缓存。"""
    response = await call_next(request)
    path = request.url.path
    if path in ("/", "/index.html") or path.startswith(("/js/", "/css/")):
        response.headers["Cache-Control"] = "no-cache"
    return response


# 登录接口限流：同一 IP 每分钟最多 30 次（进程内计数）
_login_attempts: dict = defaultdict(list)


@app.middleware("http")
async def rate_limit_login(request, call_next):
    if request.url.path == "/api/v1/auth/login" and request.method == "POST":
        ip = request.client.host if request.client else "?"
        now = time.time()
        _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < 60]
        if len(_login_attempts[ip]) >= 30:
            return JSONResponse({"detail": "请求过于频繁，请稍后再试"}, status_code=429)
        _login_attempts[ip].append(now)
    return await call_next(request)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(devices.router, prefix="/api/v1")
app.include_router(work_orders.router, prefix="/api/v1")
app.include_router(repair_requests.router, prefix="/api/v1")
app.include_router(announcements.router, prefix="/api/v1")
app.include_router(approvals.router, prefix="/api/v1")
app.include_router(maintenance.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(screen.router, prefix="/api/v1")
app.include_router(system.router, prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api/v1")
app.include_router(files.router, prefix="/api/v1")
app.include_router(twin.router, prefix="/api/v1")
app.include_router(ws.router, prefix="/api/v1")


@app.get("/api/v1/health", tags=["系统"])
def health():
    return {"status": "ok", "app": "OA"}


# 前端静态页面（需在 API 路由之后挂载）
app.mount("/", StaticFiles(directory=str(config.FRONTEND_DIR), html=True), name="frontend")
