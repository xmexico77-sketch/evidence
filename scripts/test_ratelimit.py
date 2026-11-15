"""登录失败限速的验收测试。

背景：评审账号密码写在提交材料里，属于"公开的秘密"。没有限速的话，
任何人可以拿密码表无限次试，既可能撞开后台，也会拖垮 2G 小机器。

本测试验证四件事：
1. 连续失败达到阈值后转为 429，并带 Retry-After 头；
2. 封禁期间即使密码正确也拒绝（防止从响应差异探测密码）；
3. 登录成功会清掉该账号维度的失败计数，不影响后续正常登录；
4. 不同 IP 之间互不牵连（避免一个人被刷导致所有人登不上）。

用法：.venv\\Scripts\\python.exe scripts\\test_ratelimit.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from app import ratelimit  # noqa: E402
from app.auth import users  # noqa: E402
from app.main import app  # noqa: E402

results: list[tuple[bool, str, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((cond, name, detail))


def main() -> int:
    if not users():
        print("没有配置账号，跳过")
        return 0

    username, password = next(iter(users().items()))
    client = TestClient(app)

    ratelimit.reset_all()

    # 1) 连续失败到阈值 → 429
    codes = []
    last_retry = ""
    for _ in range(ratelimit.MAX_FAILS):
        r = client.post("/api/login", json={"username": username, "password": "wrong-password"})
        codes.append(r.status_code)
        if r.status_code == 429:
            last_retry = r.headers.get("retry-after", "")

    check("前几次失败返回 401", all(c == 401 for c in codes[:-1]), str(codes))
    check("达到阈值后返回 429", codes[-1] == 429, str(codes))
    check("429 带 Retry-After 头", bool(last_retry), f"retry-after={last_retry!r}")

    # 2) 封禁期内正确密码也被拒
    r = client.post("/api/login", json={"username": username, "password": password})
    check("封禁期内正确密码同样被拒", r.status_code == 429, str(r.status_code))

    # 3) 换 IP 不受牵连
    ratelimit.reset_all()
    r = client.post(
        "/api/login",
        json={"username": username, "password": password},
        headers={"x-forwarded-for": "203.0.113.9"},
    )
    check("不同 IP 可正常登录", r.status_code == 200, str(r.status_code))

    # 4) 成功登录清零账号维度计数
    ratelimit.reset_all()
    for _ in range(ratelimit.MAX_FAILS - 1):
        client.post("/api/login", json={"username": username, "password": "wrong"},
                    headers={"x-forwarded-for": "198.51.100.7"})
    r = client.post("/api/login", json={"username": username, "password": password},
                    headers={"x-forwarded-for": "198.51.100.7"})
    check("未达阈值时正确密码可登录", r.status_code == 200, str(r.status_code))
    r = client.post("/api/login", json={"username": username, "password": "wrong"},
                    headers={"x-forwarded-for": "198.51.100.7"})
    check("成功后被清零（下一次失败仍是 401 而非 429）", r.status_code == 401, str(r.status_code))

    # 5) 来源维度：同一 IP 换用户名刷也会被封
    ratelimit.reset_all()
    codes = []
    for i in range(ratelimit.MAX_FAILS_IP):
        r = client.post("/api/login", json={"username": f"nobody{i}", "password": "x"},
                        headers={"x-forwarded-for": "192.0.2.55"})
        codes.append(r.status_code)
    check("同 IP 换用户名刷会被封", 429 in codes, f"max_ip={ratelimit.MAX_FAILS_IP} codes={codes[-3:]}")

    ok = sum(1 for c, _, _ in results if c)
    for cond, name, detail in results:
        print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if not cond and detail else ""))
    print(f"\n{ok}/{len(results)} 项通过")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
