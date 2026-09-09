"""全局配置。正式部署/比赛前请修改 SECRET_KEY 与 TWIN_API_KEY。"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
PROJECT_ROOT = BASE_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
UPLOAD_DIR = DATA_DIR / "uploads"  # 文件共享 / 工单附件存储目录

DB_PATH = DATA_DIR / "oatool.db"
DATABASE_URL = os.getenv("OATOOL_DB_URL", f"sqlite:///{DB_PATH.as_posix()}")

# 单个文件上传大小上限（MB），默认 500MB，可用环境变量调整
MAX_UPLOAD_MB = int(os.getenv("OATOOL_MAX_UPLOAD_MB", "500"))

SECRET_KEY = os.getenv("OATOOL_SECRET", "oatool-lan-2026-industrial-ops-platform-secret-key")
TOKEN_EXPIRE_HOURS = 24

# 数字孪生系统调用 OA 下发工单时，请求头需携带 X-API-Key
TWIN_API_KEY = os.getenv("TWIN_API_KEY", "twin-2026-secret")
# OA 向数字孪生回传工单状态的地址（留空则不回调）
TWIN_CALLBACK_URL = os.getenv("TWIN_CALLBACK_URL", "")
