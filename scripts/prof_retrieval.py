"""性能探针：定位索引加载/检索/重排各自的耗时。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.indexing import HybridRetriever, Store  # noqa: E402


def t(label: str, fn):  # noqa: ANN001, ANN201
    start = time.time()
    out = fn()
    print(f"  {label:<34} {time.time() - start:>7.2f}s")
    return out


def main() -> int:
    store = Store()
    t("Store 初始化", lambda: None)
    r = t("HybridRetriever 构造（读块与向量）", lambda: HybridRetriever(store))
    t("build_bm25", lambda: r.build_bm25())
    q = "future work on improving efficiency of attention"

    t("首次 search（含重排模型加载）", lambda: r.search(q, top_k=3))
    t("后续 search x1（含重排）", lambda: r.search(q, top_k=3))

    def ten_rerank() -> None:
        for _ in range(10):
            r.search(q, top_k=3)

    t("后续 search x10（含重排）", ten_rerank)

    def ten_norerank() -> None:
        for _ in range(10):
            r.search(q, top_k=3, rerank=False)

    t("后续 search x10（不含重排）", ten_norerank)

    def bm25_only() -> None:
        for _ in range(10):
            r._bm25_ranked(q, 30)

    t("bm25 x10", bm25_only)

    def dense_only() -> None:
        for _ in range(10):
            r._dense_ranked(q, 30)

    t("dense x10", dense_only)

    def rerank_only() -> None:
        from app.indexing.retriever import _reranker

        pairs = [c["text"] for c in r.chunks[:12]]
        for _ in range(10):
            list(_reranker().rerank(q, pairs))

    t("rerank x10（12 候选）", rerank_only)

    store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
