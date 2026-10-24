"""部署自检：对着一个已部署的地址跑一遍关键路径。

用途：把服务部署到公网之后，**不要靠手点判断"应该没问题"**。
这个脚本会验证：健康检查、登录（启用认证时）、文献库非空、问答返回带锚点、
四个页面可达。评审遇到问题之前，你先跑它。

用法：
  .venv\\Scripts\\python.exe scripts/check_deploy.py https://your-domain.com
  .venv\\Scripts\\python.exe scripts/check_deploy.py http://127.0.0.1:3001 --user reviewer --password review2026

退出码 0 表示全部通过，可直接用于部署流水线或开机自检。
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

results: list[tuple[bool, str, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((cond, name, detail))


class Client:
    """带 Cookie 的极简客户端，模拟浏览器访问同一个域名。"""

    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )

    def request(
        self, path: str, *, method: str = "GET", payload: dict | None = None, timeout: float = 120
    ) -> tuple[int, str]:
        data = None
        headers = {"User-Agent": "evidence-deploy-check/1.0"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        req = urllib.request.Request(
            f"{self.base}{path}", data=data, headers=headers, method=method
        )
        try:
            with self.opener.open(req, timeout=timeout) as r:
                return r.status, r.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "ignore")[:300]
        except Exception as e:  # noqa: BLE001
            return 0, f"{type(e).__name__}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base", help="站点地址，例如 https://evidence.example.com")
    ap.add_argument("--user", default="reviewer")
    ap.add_argument("--password", default="review2026")
    args = ap.parse_args()

    c = Client(args.base)
    print(f"目标：{args.base}\n")

    # 1. 健康检查（必须是公开端点，否则负载均衡探测会失败）
    code, body = c.request("/api/health", timeout=30)
    healthy = code == 200
    check("健康检查可访问（免登录）", healthy, f"{code} {body[:80]}")
    chunks = 0
    if healthy:
        try:
            data = json.loads(body)
            chunks = int(data.get("chunks") or 0)
            check("已建立索引", chunks > 0, str(chunks))
            print(f"  模型后端：{data.get('llm')}   索引块数：{chunks}")
        except Exception:  # noqa: BLE001
            check("健康检查返回 JSON", False, body[:80])

    # 2. 认证状态
    code, body = c.request("/api/me")
    auth_enabled = False
    if code == 200:
        try:
            me = json.loads(body)
            auth_enabled = bool(me.get("auth_enabled"))
        except Exception:  # noqa: BLE001
            pass
    else:
        auth_enabled = code == 401

    if auth_enabled:
        print("  认证：已启用，尝试用评审账号登录")
        code, body = c.request(
            "/api/login",
            method="POST",
            payload={"username": args.user, "password": args.password},
            timeout=30,
        )
        check("评审账号可登录", code == 200, f"{code} {body[:80]}")
        code, _ = c.request("/api/me")
        check("登录后会话有效", code == 200, str(code))
    else:
        print("  认证：未启用（AUTH_ENABLED=0）")
        check("认证未启用时公开可访问", True)

    # 3. 文献库
    code, body = c.request("/api/papers", timeout=30)
    papers = []
    if code == 200:
        try:
            papers = json.loads(body).get("papers", [])
        except Exception:  # noqa: BLE001
            pass
    check("文献库可读且非空", code == 200 and len(papers) > 0, f"{code} n={len(papers)}")
    if papers:
        print(f"  文献库：{len(papers)} 篇，示例 {papers[0]['id']}")

    # 4. 问答（核心链路，带锚点）
    code, body = c.request(
        "/api/ask",
        method="POST",
        payload={"question": "训练用了多少块 GPU，什么型号？", "top_k": 5},
        timeout=180,
    )
    ok = False
    if code == 200:
        try:
            ans = json.loads(body)
            cites = ans.get("citations") or []
            ok = bool(ans.get("grounded")) and bool(cites)
            if cites:
                print(f"  问答：有据，锚点 {cites[0]['anchor']['label']}")
        except Exception:  # noqa: BLE001
            pass
    check("问答返回带锚点的有据回答", ok, f"{code} {body[:120]}")

    # 5. 页面
    for path in ("/", "/graph", "/discover", "/write"):
        code, body = c.request(path, timeout=45)
        check(f"页面 {path} 可访问", code == 200 and "证源" in body, f"{code}")

    passed = sum(1 for ok, _, _ in results if ok)
    for ok, name, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))
    print(f"\n{passed}/{len(results)} 项通过")
    if passed == len(results):
        print("部署自检通过，可以把地址交给评审。")
        return 0
    print("自检未通过：先按上面的失败项排查，不要直接交地址。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
