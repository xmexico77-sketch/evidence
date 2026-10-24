"""引用图谱验收：结构、指标、版本合并、关键边。

用法：.venv\\Scripts\\python.exe scripts\\verify_graph.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.graph import (  # noqa: E402
    build_graph,
    compute_metrics,
    rank_foundational,
    to_cytoscape,
)
from app.indexing import Store  # noqa: E402

results: list[tuple[bool, str, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((cond, name, detail))


def main() -> int:
    store = Store()
    g, works = build_graph(store)
    works = compute_metrics(g, works)

    check("节点数 >= 12", g.number_of_nodes() >= 12, str(g.number_of_nodes()))
    check("边数 >= 25", g.number_of_edges() >= 25, str(g.number_of_edges()))
    check("图为有向", g.is_directed())
    check("无自环", not any(u == v for u, v in g.edges()))

    tr = works.get("1706.03762")
    check("Transformer 在图中", tr is not None)
    if tr:
        check("版本已合并（v1/v7 同一节点）", len(tr.members) >= 2, str(tr.members))
        check("Transformer 有被引", g.in_degree("1706.03762") >= 3, str(g.in_degree("1706.03762")))

    top = rank_foundational(works, 6)
    names = [w.title.lower() for w in top]
    check("Top-5 含 Attention Is All You Need", any("attention is all you need" in n for n in names))
    check("Top-5 含序列到序列类工作", any("sequence to sequence" in n for n in names))

    # 关键边：BERT 引用 Transformer
    check("边 BERT->Transformer 存在", g.has_edge("1810.04805", "1706.03762"))

    # 指标合理性
    bad = [w.key for w in works.values() if not (0.0 <= w.pagerank <= 1.0)]
    check("PageRank 取值范围合法", not bad, str(bad[:3]))
    check("存在多社区", len({w.community for w in works.values()}) >= 2)
    check(
        "社区编号非全 -1",
        any(w.community >= 0 for w in works.values()),
    )

    # 前端数据格式
    cy = to_cytoscape(works, g)
    check("Cytoscape 节点完整", len(cy["nodes"]) == g.number_of_nodes())
    check("Cytoscape 边完整", len(cy["edges"]) == g.number_of_edges())
    check("节点含 size 字段", all("size" in n["data"] for n in cy["nodes"]))

    matched = g.graph.get("matched_refs", 0)
    total = g.graph.get("total_refs", 0)
    check("库内引用匹配数 > 30", matched > 30, f"{matched}/{total}")

    passed = sum(1 for ok, _, _ in results if ok)
    for ok, name, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))
    print(f"\n图规模：{g.number_of_nodes()} 节点 / {g.number_of_edges()} 边 · "
          f"库内互引命中 {matched}/{total}")
    print(f"{passed}/{len(results)} 项通过")
    store.close()
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
