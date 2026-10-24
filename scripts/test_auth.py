"""认证验收：开关、登录、Cookie/Bearer 双通道、篡改拒绝。

用法：.venv\\Scripts\\python.exe scripts\\test_auth.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

# 必须在 import app 之前设置：配置在导入时读取环境变量
os.environ["AUTH_ENABLED"] = "1"
os.environ["EVIDENCE_USERS"] = "demo:demo2026,reviewer:review2026"
os.environ["EVIDENCE_SECRET"] = "test-secret-for-verification"

from fastapi.testclient import TestClient  # noqa: E402

from app.auth import create_token, verify_token  # noqa: E402
from app.main import app  # noqa: E402

results: list[tuple[bool, str, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((cond, name, detail))


def main() -> int:
    # ---- 纯函数层 ----
    tok = create_token("demo")
    check("令牌可验证", verify_token(tok) == "demo")
    check("篡改令牌被拒", verify_token(tok[:-2] + "aa") is None)
    check("空令牌被拒", verify_token("") is None)
    check("伪造签名被拒", verify_token(tok.split(".")[0] + "." + "0" * 64) is None)

    client = TestClient(app)

    # ---- 未登录 ----
    r = client.get("/api/health")
    check("健康检查公开", r.status_code == 200, str(r.status_code))
    r = client.get("/api/papers")
    check("未登录访问业务接口被拒", r.status_code == 401, str(r.status_code))

    # ---- 登录 ----
    r = client.post("/api/login", json={"username": "demo", "password": "wrong"})
    check("错误密码被拒", r.status_code == 401, str(r.status_code))
    r = client.post("/api/login", json={"username": "nobody", "password": "x"})
    check("不存在账号被拒", r.status_code == 401, str(r.status_code))

    r = client.post("/api/login", json={"username": "reviewer", "password": "review2026"})
    check("评审账号可登录", r.status_code == 200, str(r.status_code))
    token = r.json().get("token", "")
    check("登录返回令牌", len(token) > 20)
    check("登录设置 Cookie", "evidence_session" in r.cookies, str(list(r.cookies)))

    # ---- 带 Cookie 访问 ----
    r = client.get("/api/papers")
    check("带 Cookie 可访问业务接口", r.status_code == 200, str(r.status_code))

    r = client.get("/api/me")
    check("/api/me 返回当前用户", r.json().get("user") == "reviewer", str(r.json()))

    # ---- 带 Bearer 访问（无 Cookie 的新客户端）----
    fresh = TestClient(app)
    r = fresh.get("/api/papers", headers={"Authorization": f"Bearer {token}"})
    check("Bearer 令牌可用", r.status_code == 200, str(r.status_code))
    r = fresh.get("/api/papers", headers={"Authorization": "Bearer bad.token"})
    check("坏 Bearer 被拒", r.status_code == 401, str(r.status_code))

    # ---- 登出 ----
    r = client.post("/api/logout")
    check("登出成功", r.status_code == 200)
    r = client.get("/api/papers")
    check("登出后不可访问", r.status_code == 401, str(r.status_code))

    # ---- 关闭开关 ----
    os.environ["AUTH_ENABLED"] = "0"
    open_client = TestClient(app)
    r = open_client.get("/api/papers")
    check("关闭认证后可直接访问", r.status_code == 200, str(r.status_code))
    r = open_client.get("/api/me")
    check("关闭认证时 /api/me 显示 anonymous", r.json().get("user") == "anonymous")

    passed = sum(1 for ok, _, _ in results if ok)
    for ok, name, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))
    print(f"\n{passed}/{len(results)} 项通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
