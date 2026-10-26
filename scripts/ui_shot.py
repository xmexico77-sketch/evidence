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

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:  # noqa: BLE001
            pass


def capture(browser: str, port: int, pages: list[tuple[str, str]], out_dir: Path,
            width: int, height: int, wait_ms: int) -> int:
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
    try:
        ws_url = wait_devtools(port)
        ws_url = page_target(port)
        sess = Session(ws_url)
        sess.send("Page.enable")
        sess.send("Emulation.setDeviceMetricsOverride",
                  {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False})
        for name, url in pages:
            sess.send("Page.navigate", {"url": url})
            time.sleep(wait_ms / 1000)
            shot = sess.send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
            target = out_dir / f"{name}.png"
            target.write_bytes(base64.b64decode(shot["data"]))
            size_kb = target.stat().st_size / 1024
            print(f"  {name:<10} {url:<48} {size_kb:6.0f} KB")
            if size_kb > 5:
                ok += 1
        sess.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="只抓一个页面")
    ap.add_argument("--out", default="docs/preview/ui", help="输出目录（相对项目根）")
    ap.add_argument("--port", type=int, default=9333)
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=1000)
    ap.add_argument("--wait-ms", type=int, default=3500, help="每页等待渲染的时间")
    args = ap.parse_args()

    pages = [("page", args.url)] if args.url else DEFAULT_PAGES
    out_dir = (ROOT / args.out) if not Path(args.out).is_absolute() else Path(args.out)
    browser = find_browser()
    print(f"浏览器：{browser}\n输出：{out_dir}")
    ok = capture(browser, args.port, pages, out_dir, args.width, args.height, args.wait_ms)
    print(f"\n{ok}/{len(pages)} 页截图成功")
    return 0 if ok == len(pages) else 1


if __name__ == "__main__":
    sys.exit(main())
