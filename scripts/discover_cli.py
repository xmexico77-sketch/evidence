"""论文发现 CLI：检索 / 追踪 / 推荐 / 下钻入库。

用法：
  # 按关键词检索并排序（含 GitHub 可复现性加权）
  .venv\\Scripts\\python.exe scripts\\discover_cli.py search "efficient attention"

  # 追踪某分类最新论文
  .venv\\Scripts\\python.exe scripts\\discover_cli.py track cs.CL --limit 6

  # 把某篇论文下钻下载并入库
  .venv\\Scripts\\python.exe scripts\\discover_cli.py ingest 2205.14135
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.config import PDF_DIR  # noqa: E402
from app.discovery import arxiv as A  # noqa: E402
from app.discovery import humanize, ingest, recommend  # noqa: E402
from app.indexing import Store, build_chunks  # noqa: E402
from app.parsing import parse_pdf  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=6)
    s.add_argument("--no-enrich", action="store_true", help="跳过 GitHub/OpenAlex 补全（更快）")

    t = sub.add_parser("track")
    t.add_argument("category", nargs="?", default="cs.CL")
    t.add_argument("--limit", type=int, default=6)
    t.add_argument("--no-enrich", action="store_true")

    i = sub.add_parser("ingest")
    i.add_argument("arxiv_id")

    sub.add_parser("list")
    args = ap.parse_args()

    store = Store()

    if args.cmd == "ingest":
        paper = A.fetch(args.arxiv_id)
        if paper is None:
            print(f"未找到 {args.arxiv_id}")
            return 1
        info = ingest(store, paper, PDF_DIR, build_chunks, parse_pdf)
        print(f"已入库 {info['paper_id']}，{info['chunks']} 块，文件 {info['path']}")
        store.close()
        return 0

    if args.cmd == "list":
        items = store.list_discoveries(20)
        print(f"已保存推荐 {len(items)} 条")
        for d in items:
            print(f"  {d['score']:.3f}  {d['id']:<14} {d['title'][:64]}")
        store.close()
        return 0

    query = args.query if args.cmd == "search" else None
    category = getattr(args, "category", "cs.CL")
    items = recommend(
        store,
        query=query,
        category=category,
        limit=args.limit,
        enrich=not args.no_enrich,
    )
    store.save_discoveries(items)
    label = f'检索「{query}」' if query else f"追踪 {category} 最新"
    print(f"{label}：推荐 {len(items)} 条\n")
    print(humanize(items))
    store.close()
    return 0 if items else 1


if __name__ == "__main__":
    raise SystemExit(main())
