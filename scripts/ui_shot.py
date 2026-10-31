"""用无头 Edge + CDP 给页面截图。

为什么不用 `msedge --screenshot`：在本机实测该参数不产出文件
（--dump-dom 却正常），所以改走 DevTools Protocol：
启动带 --remote-debugging-port 的无头浏览器，用 WebSocket 发
Page.navigate / Page.captureScreenshot，稳定可控。

用途：
1. 开发期"看见"界面（没有真实浏览器可用时的替代方案）；
2. 为演示视频抓取各页面画面。

用法：
  .venv\\Scripts\\python.exe scripts/ui_shot.py --out docs/preview/ui
  .venv\\Scripts\\python.exe scripts/ui_shot.py --url http://127.0.0.1:3001/graph --out docs/preview/graph
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

DEFAULT_PAGES = [
    ("home", "http://127.0.0.1:3001/"),
    ("reader", "http://127.0.0.1:3001/paper/1706.03762v1"),
    ("graph", "http://127.0.0.1:3001/graph"),
    ("discover", "http://127.0.0.1:3001/discover"),
    ("write", "http://127.0.0.1:3001/write"),
]


def find_browser() -> str:
    for path in EDGE_CANDIDATES:
        if Path(path).exists():
            return path
    raise SystemExit("未找到 Edge/Chrome 可执行文件")


def wait_devtools(port: int, timeout: float = 25.0) -> None:
    """等 DevTools 端口就绪。"""
    deadline = time.time() + timeout
    last_err = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2):
                return
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)[:60]
            time.sleep(0.4)
    raise SystemExit(f"DevTools 未就绪: {last_err}")


def page_target(port: int, timeout: float = 15.0) -> str:
    """取"页面"目标的 WebSocket 地址。

    /json/version 给的是**浏览器级**连接，它不支持 Page 域
    （实测报 "Page.enable wasn't found"）；截图必须连到具体页面目标。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=3) as r:
                targets = json.loads(r.read())
            for t in targets:
                if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                    return t["webSocketDebuggerUrl"]
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.4)
    raise SystemExit("找不到可用的页面目标")


class Session:
    """极简 CDP 会话：只需 navigate 与 screenshot。"""

    def __init__(self, ws_url: str) -> None:
        from websockets.sync.client import connect

        self.ws = connect(ws_url, max_size=64 * 1024 * 1024)
        self.next_id = 0

    def send(self, method: str, params: dict | None = None, timeout: float = 40) -> dict:
        self.next_id += 1
        mid = self.next_id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = self.ws.recv(timeout=max(1.0, deadline - time.time()))
            msg = json.loads(raw)
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
        raise TimeoutError(method)

    def evaluate(self, expr: str, timeout: float = 20) -> dict:
        return self.send(
            "Runtime.evaluate",
            {"expression": expr, "awaitPromise": True, "returnByValue": True},
            timeout=timeout,
        )

    def set_file_input(self, selector: str, path: str) -> None:
        """给 <input type=file> 塞文件。

        浏览器安全限制不允许 JS 直接写 file input 的 value，
        只能走 CDP 的 DOM.setFileInputFiles。塞完 Chrome 会自动派发
        input/change 事件，React 的 onChange 能正常触发。
        """
        self.send("DOM.enable")
        doc = self.send("DOM.getDocument", {"depth": -1})
        node = self.send(
            "DOM.querySelector",
            {"nodeId": doc["root"]["nodeId"], "selector": selector},
        )
        node_id = node.get("nodeId")
        if not node_id:
            raise RuntimeError(f"找不到文件输入框：{selector}")
        self.send("DOM.setFileInputFiles", {"files": [path], "nodeId": node_id})

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:  # noqa: BLE001
            pass


def login(sess: "Session", base: str, user: str, password: str, wait_ms: int = 1500) -> bool:
    """在浏览器里调一次 /api/login 拿到会话 Cookie。

    为什么需要：后端开了认证后，未登录访问任何页面都会被前端重定向到
    /login——截图会拍成登录页（本会话踩过：以为页面坏了，其实是没登录）。
    """
    sess.send("Page.navigate", {"url": f"{base}/login"})
    time.sleep(wait_ms / 1000)
    js = (
        "fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},"
        f"body:JSON.stringify({{username:'{user}',password:'{password}'}})}})"
        ".then(r=>r.status)"
    )
    try:
        res = sess.evaluate(js, timeout=20)
        status = res.get("result", {}).get("value")
        print(f"  [login] {user} → {status}")
        return status == 200
    except Exception as exc:  # noqa: BLE001
        print(f"  [login] 失败：{exc}")
        return False


def capture(browser: str, port: int, pages: list[tuple[str, str]], out_dir: Path,
            width: int, height: int, wait_ms: int, steps: list[dict] | None = None,
            login_info: tuple[str, str, str] | None = None) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    profile = ROOT / ".cache" / f"edge-shot-{port}"
    proc = subprocess.Popen(
        [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--no-first-run",
            "--hide-scrollbars",
            f"--window-size={width},{height}",
            f"--user-data-dir={profile}",
            f"--remote-debugging-port={port}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    ok = 0
    shots = 0
    try:
        wait_devtools(port)
        ws_url = page_target(port)
        sess = Session(ws_url)
        sess.send("Page.enable")
        sess.send("Runtime.enable")
        sess.send("Emulation.setDeviceMetricsOverride",
                  {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False})

        if login_info:
            base = pages[0][1]
            base = re.sub(r"^(https?://[^/]+).*$", r"\1", base)
            login(sess, base, login_info[0], login_info[1])

        def shoot(name: str) -> None:
            nonlocal shots
            shot = sess.send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
            target = out_dir / f"{name}.png"
            target.write_bytes(base64.b64decode(shot["data"]))
            print(f"  [shot] {name:<28} {target.stat().st_size / 1024:6.0f} KB")
            shots += 1

        for name, url in pages:
            sess.send("Page.navigate", {"url": url})
            time.sleep(wait_ms / 1000)
            print(f"  [page] {name:<10} {url}")
            if not steps:
                shoot(name)
                ok += 1
                continue
            ok += 1
            for step in steps:
                if "wait" in step:
                    time.sleep(float(step["wait"]) / 1000)
                elif "eval" in step:
                    sess.evaluate(step["eval"])
                elif "file" in step:
                    sess.set_file_input(step["file"]["selector"], step["file"]["path"])
                elif "shot" in step:
                    shoot(step["shot"])
        sess.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    return ok if not steps else shots


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="只抓一个页面")
    ap.add_argument("--out", default="docs/preview/ui", help="输出目录（相对项目根）")
    ap.add_argument("--port", type=int, default=9333)
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=1000)
    ap.add_argument("--js", help="JSON 步骤数组：{\"eval\":expr}/{\"wait\":ms}/{\"shot\":name}")
    ap.add_argument("--js-file", help="同上，但从文件读（Windows 下命令行传引号会被吞）")
    ap.add_argument("--wait-ms", type=int, default=3500, help="每页等待渲染的时间")
    ap.add_argument("--login", help="账号:密码；后端启用认证时必填，否则截到的是登录页")
    args = ap.parse_args()

    pages = [("page", args.url)] if args.url else DEFAULT_PAGES
    out_dir = (ROOT / args.out) if not Path(args.out).is_absolute() else Path(args.out)
    browser = find_browser()
    steps = None
    if args.js_file:
        steps = json.loads(Path(args.js_file).read_text(encoding="utf-8"))
    elif args.js:
        steps = json.loads(args.js)
    login_info = None
    if args.login:
        user, _, pwd = args.login.partition(":")
        login_info = (user, pwd)
    print(f"浏览器：{browser}\n输出：{out_dir}")
    ok = capture(browser, args.port, pages, out_dir, args.width, args.height, args.wait_ms,
                 steps, login_info)
    unit = "张截图" if steps else "页截图"
    total = len(steps and [s for s in steps if "shot" in s]) or len(pages)
    print(f"\n{ok}/{total} {unit}成功")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
