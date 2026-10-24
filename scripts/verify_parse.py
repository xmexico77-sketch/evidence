"""解析质量验收：把"看起来对"变成"断言通过"。

这是 make verify 的雏形——评审要的是可复现，不是截图。
用法：.venv\\Scripts\\python.exe scripts\\verify_parse.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARSED = ROOT / "data" / "parsed"

# 官方测试用例 3.1：Attention Is All You Need v1
EXPECT_V1 = {
    "title": "Attention Is All You Need",
    "min_references": 38,
    "min_citations": 30,
    "required_headings": [
        "1",
        "2",
        "3",
        "3.1",
        "3.2",
        "3.2.1",
        "3.3",
        "4",
        "5",
        "5.1",
        "5.3",
        "6",
        "6.1",
        "7",
    ],
    "required_phrases": [
        "The encoder is composed of a stack of N = 6 identical layers",
        "The dominant sequence transduction models",
        "We trained on the standard WMT 2014 English-German dataset",
    ],
    "min_abstract_chars": 500,
}


def load(paper_id: str) -> dict:
    path = PARSED / f"{paper_id}.json"
    if not path.exists():
        raise SystemExit(f"缺少解析产物 {path}，先跑 scripts/parse_cli.py")
    return json.loads(path.read_text(encoding="utf-8"))


def check(paper: dict, expect: dict) -> list[str]:
    failures: list[str] = []
    text = " ".join(b["text"] for b in paper["blocks"])

    if expect.get("title") and paper["title"] != expect["title"]:
        failures.append(f"标题不符: {paper['title']!r} != {expect['title']!r}")
    if len(paper["references"]) < expect["min_references"]:
        failures.append(
            f"参考文献过少: {len(paper['references'])} < {expect['min_references']}"
        )
    if len(paper["citations"]) < expect["min_citations"]:
        failures.append(f"引用标记过少: {len(paper['citations'])} < {expect['min_citations']}")
    if len(paper["abstract"]) < expect["min_abstract_chars"]:
        failures.append(
            f"摘要过短: {len(paper['abstract'])} < {expect['min_abstract_chars']}"
        )

    numbers = {h["number"] for h in paper["headings"] if h["number"]}
    for need in expect["required_headings"]:
        if need not in numbers:
            failures.append(f"缺少章节: {need}")

    for phrase in expect["required_phrases"]:
        if phrase not in text:
            failures.append(f"正文缺失（或空格重建失败）: {phrase[:60]!r}")

    # 阅读顺序：摘要必须出现在 Introduction 之前
    order = {b["id"]: b["order"] for b in paper["blocks"]}
    by_num = {h["number"]: order.get(h["block_id"], -1) for h in paper["headings"] if h["number"]}
    if "1" in by_num and "3" in by_num and by_num["1"] > by_num["3"]:
        failures.append("阅读顺序错误: Introduction 出现在 Model Architecture 之后")
    if "3.1" in by_num and "3.2" in by_num and by_num["3.1"] > by_num["3.2"]:
        failures.append("阅读顺序错误: 3.1 出现在 3.2 之后")

    # 锚点完整性：每个块都要有页号和 bbox
    for blk in paper["blocks"]:
        if not blk.get("bbox") or len(blk["bbox"]) != 4:
            failures.append(f"锚点缺失 bbox: {blk['id']}")
            break
        if not (1 <= blk["page"] <= paper["page_count"]):
            failures.append(f"锚点页码越界: {blk['id']} p{blk['page']}")
            break
    return failures


def main() -> int:
    total_fail = 0
    for paper_id, expect in {"1706.03762v1": EXPECT_V1}.items():
        paper = load(paper_id)
        failures = check(paper, expect)
        status = "PASS" if not failures else "FAIL"
        print(f"[{status}] {paper_id}  "
              f"pages={paper['page_count']} blocks={len(paper['blocks'])} "
              f"headings={len(paper['headings'])} refs={len(paper['references'])} "
              f"cites={len(paper['citations'])}")
        for f in failures:
            print(f"   - {f}")
        total_fail += len(failures)
    print(f"\n总计失败断言: {total_fail}")
    return 1 if total_fail else 0


if __name__ == "__main__":
    sys.exit(main())
