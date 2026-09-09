"""密码哈希与 JWT 令牌。"""
import hashlib
import hmac
import os
import time

import jwt

from . import config

_ITERATIONS = 120_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return f"pbkdf2${_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def create_token(user) -> str:
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        "exp": int(time.time()) + config.TOKEN_EXPIRE_HOURS * 3600,
    }
    return jwt.encode(payload, config.SECRET_KEY, algorithm="HS256")


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, config.SECRET_KEY, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


# ---------- 登录失败锁定（进程内计数：5 次失败锁 15 分钟） ----------
import threading as _threading

_login_lock = _threading.Lock()
_failed: dict = {}  # username -> [fail_count, locked_until_ts]

MAX_FAILURES = 5
LOCK_SECONDS = 15 * 60


def is_locked(username: str) -> tuple[bool, int]:
    """返回 (是否锁定, 剩余秒数)。"""
    with _login_lock:
        rec = _failed.get(username)
        if not rec or rec[1] == 0:  # rec[1]=0 表示尚未触发锁定（仅计数）
            return False, 0
        remain = int(rec[1] - time.time())
        if remain <= 0:
            _failed.pop(username, None)
            return False, 0
        return True, remain


def register_failure(username: str) -> None:
    with _login_lock:
        rec = _failed.get(username) or [0, 0]
        rec[0] += 1
        if rec[0] >= MAX_FAILURES:
            rec[1] = time.time() + LOCK_SECONDS
            rec[0] = 0
        _failed[username] = rec


def clear_failures(username: str) -> None:
    with _login_lock:
        _failed.pop(username, None)
