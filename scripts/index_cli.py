"""索引 CLI：解析 -> 分块 -> 入库 -> 建索引 -> 试检索。

用法：
  # 建库（可重复执行，按 paper id 覆盖）
  .venv\\Scripts\\python.exe scripts\\index_cli.py build data/pdf/1706.03762v1.pdf

  # 试检索（含跨语言）
  .venv\\Scripts\\python.exe scripts\\index_cli.py query "Transformer 训练用了多少块 GPU？"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.indexing import HybridRetriever, Store, build_chunks, chunk_stats, format_hits  # noqa: E402
from app.parsing import parse_pdf, summary  # noqa: E402


def _resolve(pattern: str) -> list[Path]:
    """相对路径一律按项目根解析，避免受调用方工作目录影响。"""
    p = Path(pattern)
    if "*" in pattern:
        return sorted(ROOT.glob(pattern))
    return [p if p.is_absolute() else ROOT / p]


def cmd_build(paths: list[str]) -> int:
    store = Store()
    for raw in paths:
        for path in _resolve(raw):
            print(f"[parse] {path.name}")
            paper = parse_pdf(path)
            stats = summary(paper)
            chunks = build_chunks(paper)
            cstats = chunk_stats(chunks)
            store.upsert_paper(paper, chunks)
            print(
                f"  headings={stats['headings']} refs={stats['references']} "
                f"chunks={cstats['count']} avg={cstats['avg_chars']}chars "
                f"sections={cstats['sections']}"
            )

    retriever = HybridRetriever(store)
    retriever.build_bm25()
    print(f"[bm25] ready over {len(retriever.chunks)} chunks")
    added = retriever.embed_missing()
    print(f"[dense] embedded {added} chunks, matrix={retriever._vecs.shape}")

    for paper in store.list_papers():
        print(f"  · {paper['id']}  {paper['title'][:60]}  chunks={paper['chunks']}")
    store.close()
    return 0


def cmd_query(query: str, top_k: int) -> int:
    store = Store()
    retriever = HybridRetriever(store)
    retriever.build_bm25()
    hits = retriever.search(query, top_k=top_k)
    print(f"\n查询：{query}")
    print(format_hits(hits))
    if hits:
        top = hits[0]
        print(f"\n最佳锚点：{top['anchor']}")
        print(f"bbox={top['bbox']}  page={top['page_start']}  chunk={top['id']}")
    store.close()
    return 0 if hits else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("pdfs", nargs="+")
    q = sub.add_parser("query")
    q.add_argument("query")
    q.add_argument("--top-k", type=int, default=5)
    args = ap.parse_args()

    if args.cmd == "build":
        return cmd_build(args.pdfs)
    return cmd_query(args.query, args.top_k)


if __name__ == "__main__":
    raise SystemExit(main())
