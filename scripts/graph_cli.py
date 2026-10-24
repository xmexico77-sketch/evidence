"""图谱 CLI：建图、算指标、导出前端数据。

用法：
  .venv\\Scripts\\python.exe scripts\\graph_cli.py            # 建图并打印榜单
  .venv\\Scripts\\python.exe scripts\\graph_cli.py --json     # 额外导出 Cytoscape JSON
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.config import INDEX_DIR  # noqa: E402
from app.graph import (  # noqa: E402
    build_graph,
    compute_metrics,
    rank_derivative,
    rank_foundational,
    to_cytoscape,
)
from app.indexing import Store  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="导出 Cytoscape JSON")
    ap.add_argument("--top", type=int, default=6)
    args = ap.parse_args()

    store = Store()
    g, works = build_graph(store)
    works = compute_metrics(g, works)

    matched = g.graph.get("matched_refs", 0)
    total = g.graph.get("total_refs", 0)
    rate = (matched / total * 100) if total else 0.0
    print(f"节点 {g.number_of_nodes()} · 边 {g.number_of_edges()} · "
          f"库内引用命中 {matched}/{total}（{rate:.1f}%）\n")

    print(f"{'排名':<4}{'论文':<52}{'年':<6}{'PR':>9}{'持续':>7}{'基石分':>9}{'社区':>6}")
    print("-" * 94)
    for i, w in enumerate(rank_foundational(works, args.top), 1):
        print(f"{i:<4}{w.title[:50]:<52}{w.year or '-':<6}"
              f"{w.pagerank:>9.5f}{w.sustained:>7.2f}{w.foundational:>9.5f}{w.community:>6}")

    print("\n--- 边缘衍生（引用多、被引少）---")
    for w in rank_derivative(works, args.top):
        print(f"  {w.title[:58]:<60} PR={w.pagerank:.5f} 出度贡献={w.derivative:.3f}")

    print("\n--- 社区划分 ---")
    by_community: dict[int, list[str]] = {}
    for w in works.values():
        by_community.setdefault(w.community, []).append(w.title[:36])
    for cid, titles in sorted(by_community.items()):
        print(f"  社区 {cid}: {len(titles)} 篇 -> {', '.join(titles[:4])}")

    if args.json:
        payload = to_cytoscape(works, g)
        out = INDEX_DIR / "citation_graph.json"
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n已导出 {out}")

    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
