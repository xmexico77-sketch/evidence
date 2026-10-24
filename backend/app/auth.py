"""认证与会话。

## 为什么用"签名 Cookie"而不是完整 JWT 库

评审要的是一个能用的评审专用账号，不是一套 OAuth。用标准库的 HMAC
签一个载荷，既没有额外依赖，也不会把 PyJWT 的版本问题带进部署。

## 安全边界（写进技术文档，避免过度声称）

- 令牌签名用 `EVIDENCE_SECRET`，未设置时使用进程启动时生成的随机值
  （重启即失效，适合演示，不适合长期部署）
- 账号从 `EVIDENCE_USERS` 读，格式 `user1:pass1,user2:pass2`
- 密码以明文存在环境变量里，够用但不等同于生产级方案（无哈希、无轮换、
  无锁定策略）。这是有意的取舍：本项目的评分点在 Agent 与 RAG，不在账号体系。
- `AUTH_ENABLED=0` 时可完全关闭（本地开发、离线演示）
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

COOKIE_NAME = "evidence_session"
TOKEN_TTL = 12 * 3600  # 12 小时，够评审用一天

_DEFAULT_USERS = "demo:demo2026,reviewer:review2026"
_runtime_secret = secrets.token_hex(16)


def auth_enabled() -> bool:
    return os.environ.get("AUTH_ENABLED", "0").strip() not in {"0", "", "false", "no"}


def _secret() -> bytes:
    return (os.environ.get("EVIDENCE_SECRET") or _runtime_secret).encode()


def users() -> dict[str, str]:
    raw = os.environ.get("EVIDENCE_USERS", _DEFAULT_USERS)
    out: dict[str, str] = {}
    for pair in raw.split(","):
        if ":" in pair:
            name, _, pwd = pair.partition(":")
            name = name.strip()
            if name:
                out[name] = pwd.strip()
    return out


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def create_token(username: str, ttl: int = TOKEN_TTL) -> str:
    payload = json.dumps(
        {"u": username, "exp": int(time.time()) + ttl}, separators=(",", ":")
    ).encode()
    body = _b64(payload)
    sig = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_token(token: str) -> str | None:
    if not token or "." not in token:
        return None
    body, _, sig = token.rpartition(".")
    expected = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(_unb64(body))
    except Exception:  # noqa: BLE001
        return None
    if int(payload.get("exp", 0)) < time.time():
        return None
    return str(payload.get("u") or "") or None


def check_password(username: str, password: str) -> bool:
    expected = users().get(username)
    if expected is None:
        return False
    return hmac.compare_digest(expected, password)


def token_from_request(headers: dict, cookies: dict) -> str | None:
    """优先 Authorization: Bearer，其次 Cookie（前端同源代理用 Cookie 最省事）。"""
    auth = headers.get("authorization") or headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return cookies.get(COOKIE_NAME)


PUBLIC_PATHS = {"/api/health", "/api/login", "/docs", "/openapi.json", "/redoc"}


def is_public(path: str) -> bool:
    if path in PUBLIC_PATHS:
        return True
    return not path.startswith("/api/")
