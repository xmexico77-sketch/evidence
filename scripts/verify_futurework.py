"""Idea 考古与自动综述验收。

重点关注"安全性质"：没有模型时不得下"已解决"结论；
所有证据必须来自原论文之后的文献。

用法：.venv\\Scripts\\python.exe scripts\\verify_futurework.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.graph import build_graph, compute_metrics  # noqa: E402
from app.graph.future import (  # noqa: E402
    STATUS_OPEN,
    STATUS_PARTIAL,
    STATUS_SOLVED,
    STATUS_UNKNOWN,
    assess_items,
    cluster_items,
    extract_future_work,
    summarize_order,
)
from app.graph.review import build_area_reviews  # noqa: E402
from app.indexing import HybridRetriever, Store  # noqa: E402

results: list[tuple[bool, str, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((cond, name, detail))


def main() -> int:
    started = time.time()
    store = Store()
    g, works = build_graph(store)
    works = compute_metrics(g, works)

    year_by_paper: dict[str, int] = {}
    for work in works.values():
        for pid in work.members:
            year_by_paper[pid] = work.year

    items = extract_future_work(store, year_by_paper)
    check("抽取 Future Work 条数 >= 15", len(items) >= 15, str(len(items)))
    check(
        "每条都有出处（paper/page/bbox）",
        all(it.paper_id and it.page > 0 and len(it.bbox) == 4 for it in items),
    )
    check(
        "不收录数据/代码声明类句子",
        not any("we release our data" in it.text.lower() for it in items),
    )
    check(
        "Transformer 有未来工作陈述",
        any(it.paper_id.startswith("1706.03762") for it in items),
    )

    n_clusters = cluster_items(items)
    check("聚类数 >= 5", n_clusters >= 5, str(n_clusters))
    check("每条都有聚类编号", all(it.cluster >= 0 for it in items))

    retriever = HybridRetriever(store)
    retriever.build_bm25()
    items = assess_items(items, retriever, year_by_paper, llm=None)

    # 安全性：无模型时绝不允许出现"疑似已解决"
    check(
        "无模型时不下已解决结论",
        all(it.status != STATUS_SOLVED for it in items),
        str([it.id for it in items if it.status == STATUS_SOLVED][:3]),
    )
    check(
        "状态取值合法",
        all(it.status in {STATUS_SOLVED, STATUS_PARTIAL, STATUS_OPEN, STATUS_UNKNOWN} for it in items),
    )
    # 时间约束：证据必须来自更晚的文献
    violations = [
        it.id
        for it in items
        for ev in it.evidence
        if year_by_paper.get(ev["paper_id"], 0) <= it.year
    ]
    check("证据严格晚于原论文", not violations, str(violations[:3]))

    open_items = summarize_order(items, 5)
    check("待探索清单非空", len(open_items) > 0, str(len(open_items)))
    check("待探索清单只含未发现证据项", all(it.status == STATUS_OPEN for it in open_items))

    reviews = build_area_reviews(works, store, llm=None)
    check("综述聚类数 >= 2", len(reviews) >= 2, str(len(reviews)))
    check("每个综述 >= 3 篇文献", all(len(r.members) >= 3 for r in reviews))
    check("每个综述都带证据", all(r.evidence for r in reviews))
    check("无模型时标注为结构式", all(r.method == "extractive" for r in reviews))

    elapsed = time.time() - started
    passed = sum(1 for ok, _, _ in results if ok)
    for ok, name, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))
    print(f"\nFuture Work {len(items)} 条 / {n_clusters} 类 · 综述 {len(reviews)} 篇 · 耗时 {elapsed:.1f}s")
    print(f"{passed}/{len(results)} 项通过")
    store.close()
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
