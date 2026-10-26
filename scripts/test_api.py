"""服务层冒烟测试：不起服务器，用 TestClient 打真实路由。

用法：.venv\\Scripts\\python.exe scripts\\test_api.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

results: list[tuple[bool, str, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((cond, name, detail))


def main() -> int:
    client = TestClient(app)

    r = client.get("/api/health")
    check("health 200", r.status_code == 200, str(r.status_code))
    body = r.json()
    check("health 报告块数", body.get("chunks", 0) > 0, str(body))

    r = client.get("/api/papers")
    check("papers 200", r.status_code == 200)
    papers = r.json().get("papers", [])
    check("知识库非空", len(papers) >= 1, str(papers)[:200])

    r = client.post("/api/search", json={"question": "训练用了多少块 GPU？", "top_k": 3})
    check("search 200", r.status_code == 200)
    hits = r.json()
    check("search 有命中", len(hits) > 0)
    if hits:
        anchor = hits[0]["anchor"]
        check("search 带锚点页码", isinstance(anchor.get("page"), int), str(anchor))
        check("search 带 bbox", len(anchor.get("bbox", [])) == 4, str(anchor))

    # 库里多篇论文都有"GPU 型号"这类陈述，必须限定论文才有确定答案。
    # 不限定时的行为由下面的"跨论文"用例单独覆盖。
    r = client.post(
        "/api/ask",
        json={"question": "训练用了多少块 GPU，什么型号？", "paper_id": "1706.03762v1"},
    )
    check("ask 200", r.status_code == 200)
    ans = r.json()
    check("ask 有答案", len(ans.get("answer", "")) > 10)
    check("ask 有引用", len(ans.get("citations", [])) >= 1, str(ans)[:300])
    check("ask 标记为有据", ans.get("grounded") is True, str(ans.get("grounded")))
    if ans.get("citations"):
        c = ans["citations"][0]
        check("引用标记为 E 型", c["marker"].startswith("[E"), c["marker"])
        check("引用有页码与 bbox", c["anchor"]["page"] > 0 and len(c["anchor"]["bbox"]) == 4)

    # 越界问题应拒答而不是编造
    r = client.post("/api/ask", json={"question": "这篇论文的作者获得过几次图灵奖？"})
    check("越界问题 200", r.status_code == 200)
    ans2 = r.json()
    check(
        "越界问题不伪装有据",
        ans2.get("grounded") is False,
        f"grounded={ans2.get('grounded')} answer={ans2.get('answer','')[:80]}",
    )

    r = client.post("/api/ask/stream", json={"question": "标签平滑取值是多少？"})
    check("stream 200", r.status_code == 200)
    check("stream 事件协议", '"type": "done"' in r.text, r.text[:120])

    # 限定论文提问：库大了之后同一问题有多个合理答案，必须能收窄范围
    r = client.post(
        "/api/ask",
        json={"question": "训练用了多少块 GPU？", "paper_id": "1706.03762v1"},
    )
    check("限定论文问答 200", r.status_code == 200, str(r.status_code))
    if r.status_code == 200:
        ans3 = r.json()
        papers = {c["anchor"]["paper_id"] for c in ans3.get("citations", [])}
        check(
            "引用只来自指定论文",
            papers == {"1706.03762v1"},
            str(papers),
        )

    # 跨论文对比（需要模型；未配置密钥时应返回 400 而不是 500）
    from app.llm import has_key

    r = client.post(
        "/api/compare",
        json={
            "dimension": "自注意力机制的作用",
            "paper_ids": ["1706.03762v1", "1810.04805"],
            "top_k": 2,
        },
    )
    if has_key():
        check("跨论文对比 200", r.status_code == 200, f"{r.status_code} {r.text[:120]}")
        if r.status_code == 200:
            data = r.json()
            check("对比返回表格", "|" in data.get("answer", ""), data.get("answer", "")[:80])
            check("对比标记合法", data.get("invalid_markers") == [], str(data.get("invalid_markers")))
    else:
        check("无模型时对比返回 400", r.status_code == 400, str(r.status_code))

    # CSV -> 学术图表（模块六）
    csv_path = ROOT / "data" / "samples" / "training_curves.csv"
    if csv_path.exists():
        r = client.post(
            "/api/charts",
            files={"file": ("training_curves.csv", csv_path.read_bytes(), "text/csv")},
        )
        check("charts 200", r.status_code == 200, f"{r.status_code} {r.text[:160]}")
        if r.status_code == 200:
            data = r.json()
            check("charts 返回图注", len(data.get("caption", "")) > 20)
            check("charts 返回脚本", data.get("script", "").endswith(".py"))
            check("charts 返回 PNG 名", data.get("png", "").endswith(".png"))
            check("charts 给出选型理由", len(data.get("reason", "")) > 4)
    else:
        check("示例 CSV 缺失", False, str(csv_path))

    passed = sum(1 for ok, _, _ in results if ok)
    for ok, name, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))
    print(f"\n{passed}/{len(results)} 项通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
