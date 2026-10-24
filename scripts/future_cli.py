"""Idea 考古 + 自动综述 CLI。

用法：
  .venv\\Scripts\\python.exe scripts/future_cli.py
  .venv\\Scripts\\python.exe scripts/future_cli.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.config import INDEX_DIR  # noqa: E402
from app.graph import build_graph, compute_metrics  # noqa: E402
from app.graph.future import (  # noqa: E402
    STATUS_OPEN,
    STATUS_SOLVED,
    STATUS_UNKNOWN,
    assess_items,
    cluster_items,
    extract_future_work,
    summarize_order,
)
from app.graph.review import build_area_reviews  # noqa: E402
from app.indexing import HybridRetriever, Store  # noqa: E402
from app.llm import DeepSeekClient, has_key  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--top", type=int, default=6)
    args = ap.parse_args()

    store = Store()
    g, works = build_graph(store)
    works = compute_metrics(g, works)

    year_by_paper: dict[str, int] = {}
    for work in works.values():
        for pid in work.members:
            year_by_paper[pid] = work.year

    items = extract_future_work(store, year_by_paper)
    n_clusters = cluster_items(items)

    retriever = HybridRetriever(store)
    retriever.build_bm25()
    llm = DeepSeekClient() if has_key() else None
    items = assess_items(items, retriever, year_by_paper, llm=llm)

    counts: dict[str, int] = {}
    for it in items:
        counts[it.status] = counts.get(it.status, 0) + 1
    print(f"抽取 Future Work {len(items)} 条，聚为 {n_clusters} 类")
    print(f"状态分布：{counts}")
    print(f"模型：{'DeepSeek' if llm else '未配置（仅证据打分，不做判定）'}\n")

    print(f"--- 仍值得探索的方向（Top {args.top}）---")
    for it in summarize_order(items, args.top):
        print(f"  · [{it.year}] {it.paper_id} p{it.page}")
        print(f"    {it.text[:150]}…")
        print(f"    状态={it.status} 证据分={it.score:.2f} 同类提及={sum(1 for x in items if x.cluster == it.cluster)}")

    solved = [it for it in items if it.status == STATUS_SOLVED]
    if solved:
        print(f"\n--- 疑似已被后续工作解决（{len(solved)} 条，建议不再投入）---")
        for it in solved[:5]:
            ev = it.evidence[0] if it.evidence else {}
            print(f"  · [{it.year}] {it.text[:110]}…")
            print(f"    → 证据：{ev.get('paper_id')} p{ev.get('page')} §{ev.get('section')} "
                  f"(score={ev.get('score')})")

    reviews = build_area_reviews(works, store, llm=llm)
    print(f"\n--- 自动综述（{len(reviews)} 个聚类）---")
    for rev in reviews:
        print(f"  聚类 {rev.community} · {rev.year_range} · {len(rev.members)} 篇 · 方式={rev.method}")
        print(f"    主题：{rev.theme[:70]}")
        print(f"    {rev.summary[:260]}")
        print()

    if args.json:
        payload = {
            "future_work": [
                {
                    "id": it.id,
                    "paper_id": it.paper_id,
                    "year": it.year,
                    "page": it.page,
                    "text": it.text,
                    "cluster": it.cluster,
                    "status": it.status,
                    "score": it.score,
                    "evidence": it.evidence,
                }
                for it in items
            ],
            "reviews": [
                {
                    "community": r.community,
                    "theme": r.theme,
                    "members": r.members,
                    "year_range": r.year_range,
                    "summary": r.summary,
                    "method": r.method,
                    "evidence": r.evidence,
                }
                for r in reviews
            ],
            "stats": {"items": len(items), "clusters": n_clusters, "status": counts},
        }
        out = INDEX_DIR / "future_work.json"
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"已导出 {out}")

    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
