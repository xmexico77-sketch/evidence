"""演示彩排：把视频里要演示的每个镜头按顺序跑一遍。

作用有两个：
1. 确认分镜脚本里写的每个画面确实可复现（不是录制时才发现跑不通）；
2. 给出每个镜头的真实耗时，用来校准视频时间轴。

用法：.venv\\Scripts\\python.exe scripts/demo_rehearsal.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "http://127.0.0.1:8000"
WEB = "http://127.0.0.1:3001"

shots: list[tuple[str, bool, float, str]] = []


def _get(path: str, timeout: float = 60) -> tuple[int, dict | list | None, str]:
    try:
        with urllib.request.urlopen(f"{API}{path}", timeout=timeout) as r:
            body = r.read().decode("utf-8", "ignore")
            return r.status, json.loads(body) if body else None, body
    except urllib.error.HTTPError as e:
        return e.code, None, e.read().decode("utf-8", "ignore")[:200]
    except Exception as e:  # noqa: BLE001
        return 0, None, str(e)[:200]


def _post(path: str, payload: dict, timeout: float = 120) -> tuple[int, dict | None, str]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{API}{path}", data=data, headers={"Content-Type": "application/json; charset=utf-8"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "ignore")
            return r.status, json.loads(body) if body else None, body
    except urllib.error.HTTPError as e:
        return e.code, None, e.read().decode("utf-8", "ignore")[:200]
    except Exception as e:  # noqa: BLE001
        return 0, None, str(e)[:200]


def shot(name: str, ok: bool, started: float, detail: str = "") -> None:
    shots.append((name, ok, time.time() - started, detail))
    mark = "OK  " if ok else "FAIL"
    print(f"[{mark}] {name}  ({time.time() - started:.1f}s)  {detail}")


def main() -> int:
    t = time.time()
    code, data, raw = _get("/api/health", timeout=20)
    ok = code == 200 and isinstance(data, dict) and data.get("ok")
    shot("镜头 0 · 服务健康", bool(ok), t, str(data)[:80] if data else raw)

    t = time.time()
    code, data, raw = _get("/api/papers")
    papers = (data or {}).get("papers", []) if isinstance(data, dict) else []
    shot("镜头 1 · 文献库列表", code == 200 and len(papers) > 0, t, f"{len(papers)} 篇")

    t = time.time()
    code, data, raw = _post(
        "/api/ask", {"question": "训练用了多少块 GPU，什么型号？", "top_k": 5}, timeout=180
    )
    ans = data or {}
    ok = code == 200 and ans.get("grounded") and ans.get("citations")
    anchor = ans.get("citations", [{}])[0].get("anchor", {}) if ans.get("citations") else {}
    shot("镜头 2 · 有据问答 + 锚点", bool(ok), t, f"{anchor.get('label', raw)[:60]}")

    t = time.time()
    code, data, raw = _post(
        "/api/ask", {"question": "这篇论文的作者获得过几次图灵奖？", "top_k": 5}, timeout=180
    )
    ans2 = data or {}
    ok = code == 200 and ans2.get("grounded") is False and ans2.get("insufficient")
    shot("镜头 3 · 越界问题拒答", bool(ok), t, (ans2.get("answer") or raw)[:60])

    t = time.time()
    code, data, raw = _get("/api/papers/1706.03762v1/outline")
    outline = (data or {}).get("outline", []) if isinstance(data, dict) else []
    shot("镜头 4 · 阅读器标题树", code == 200 and len(outline) >= 10, t, f"{len(outline)} 个标题")

    t = time.time()
    code, data, raw = _get("/api/papers/1706.03762v1/paragraphs")
    paras = (data or {}).get("paragraphs", []) if isinstance(data, dict) else []
    shot("镜头 5 · 段落级正文", code == 200 and len(paras) >= 50, t, f"{len(paras)} 段")

    t = time.time()
    code, data, raw = _post(
        "/api/translate",
        {"paper_id": "1706.03762v1", "lang": "zh", "block_ids": [p["id"] for p in paras[:5]]},
        timeout=60,
    )
    enabled = (data or {}).get("enabled")
    shot(
        "镜头 6 · 翻译接口（无 Key 时明确关闭）",
        code == 200 and enabled is False,
        t,
        "enabled=false（未配置模型）" if enabled is False else str((data or raw))[:60],
    )

    t = time.time()
    code, data, raw = _get("/api/graph", timeout=60)
    g = data or {}
    ok = code == 200 and g.get("stats", {}).get("nodes", 0) >= 10 and g.get("foundational")
    shot("镜头 7 · 引用图谱数据", bool(ok), t, f"{g.get('stats', {}).get('nodes')} 节点")

    t = time.time()
    code, data, raw = _get("/api/graph/review", timeout=300)
    rv = data or {}
    ok = code == 200 and len(rv.get("reviews", [])) >= 2 and rv.get("open_ideas")
    shot(
        "镜头 8 · 自动综述 + Idea 考古",
        bool(ok),
        t,
        f"{len(rv.get('reviews', []))} 篇综述 / {len(rv.get('open_ideas', []))} 条待探索",
    )

    t = time.time()
    code, data, raw = _get("/api/discover?q=efficient%20attention&limit=3&enrich=false", timeout=180)
    items = (data or {}).get("items", []) if isinstance(data, dict) else []
    ok = code == 200 and len(items) >= 1
    shot("镜头 9 · arXiv 检索与推荐", bool(ok), t, f"{len(items)} 条推荐")

    t = time.time()
    sample = ROOT / "data" / "samples" / "training_curves.csv"
    boundary = "----demo"
    payload = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="training_curves.csv"\r\n'
        f"Content-Type: text/csv\r\n\r\n"
    ).encode() + sample.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{API}/api/charts",
        data=payload,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            chart = json.loads(r.read().decode())
        ok = r.status == 200 and chart.get("caption")
        detail = f"{chart.get('kind')} · {chart.get('png')}"
    except Exception as e:  # noqa: BLE001
        ok, detail = False, str(e)[:60]
    shot("镜头 10 · CSV 生成学术图表", bool(ok), t, detail)

    for page, name in (
        ("/", "工作台"),
        ("/paper/1706.03762v1", "阅读器"),
        ("/graph", "图谱页"),
        ("/discover", "发现页"),
    ):
        t = time.time()
        try:
            with urllib.request.urlopen(f"{WEB}{page}", timeout=30) as r:
                code = r.status
        except Exception:  # noqa: BLE001
            code = 0
        shot(f"镜头 11 · 页面 /{'' if page == '/' else page.lstrip('/')}（{name}）", code == 200, t)

    passed = sum(1 for _, ok, _, _ in shots if ok)
    total_time = sum(s[2] for s in shots)
    print(f"\n{passed}/{len(shots)} 个镜头可复现 · 累计耗时 {total_time:.0f}s")
    if passed < len(shots):
        print("有镜头跑不通，先修再录。")
        return 1
    print("可以开录。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
