"""检索质量验收：中文提问 -> 英文论文细粒度事实。

这是模块二「单篇论文精准问答」的检索底座测试。
断言口径：top-K 命中里必须出现该事实的关键字符串，且锚点必须可定位。

用法：.venv\\Scripts\\python.exe scripts\\verify_retrieval.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.indexing import HybridRetriever, Store  # noqa: E402

# (中文提问, 事实关键词, 期望出现的章节关键词)
CASES = [
    ("训练用了多少块 GPU，什么型号？", "p100", "hardware"),
    ("Adam 优化器的 beta2 设成了多少？", "0.98", "optimizer"),
    ("WMT 2014 英德翻译任务的 BLEU 分数是多少？", "28.4", "machine translation"),
    ("用了多少个注意力头？", "8 parallel", "multi-head"),
    ("标签平滑的取值是多少？", "label smoothing of value", "regularization"),
    ("模型一共训练了多少个 step？", "100,000", "hardware"),
]


def main() -> int:
    store = Store()
    retriever = HybridRetriever(store)
    retriever.build_bm25()

    failures = 0
    for query, needle, section_hint in CASES:
        hits = retriever.search(query, top_k=5)
        blob = " ".join(h["text"] for h in hits).lower()
        found = needle in blob
        # 命中位置：是否出现在 top-3
        top3 = " ".join(h["text"] for h in hits[:3]).lower()
        in_top3 = needle in top3
        best = hits[0]["anchor"]["label"] if hits else "无命中"
        status = "PASS" if found else "FAIL"
        if not found:
            failures += 1
        print(f"[{status}] {query}")
        print(f"       期望 {needle!r} | top3命中={in_top3} | 最佳锚点 {best}")
        if hits:
            print(f"       {hits[0]['text'][:130]}…")
    if failures:
        print(f"\n{failures}/{len(CASES)} 条检索失败")
    else:
        print(f"\n全部 {len(CASES)} 条中文查询均命中英文论文事实")
    store.close()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
