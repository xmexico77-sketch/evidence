"""长文档鲁棒性压测：507 页、38MB。

赛题点名《Understanding Deep Learning》541 页，这一项测的就是规模：
解析耗时、峰值内存、分块数量、索引成本、以及"规模上去了问答还能不能用"。

设计取舍：**不写入主索引**。压测要能随时重跑，不该污染演示用的库；
稠密向量只抽样 200 块来外推全量成本，避免为了测一个数字等几分钟。

用法：.venv\\Scripts\\python.exe scripts/test_longdoc.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.indexing.chunker import build_chunks, chunk_stats  # noqa: E402
from app.parsing import parse_pdf, summary  # noqa: E402

DOC = ROOT / "data" / "longdoc" / "longdoc.pdf"

MAX_PARSE_SEC = 360.0  # 与文档承诺的"冷启动解析 ≤6 分钟"一致（实测 507 页约 335s）
MAX_PEAK_MB = 2000.0
SAMPLE_EMBED = 200
MAX_EXTRAPOLATED_EMBED_SEC = 420.0
MAX_CHUNK_CHARS = 1200

results: list[tuple[bool, str, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((cond, name, detail))


def rss_mb() -> float:
    return psutil.Process(os.getpid()).memory_info().rss / 1e6


def main() -> int:
    if not DOC.exists():
        raise SystemExit(f"缺少 {DOC}，先跑 scripts/fetch_longdoc.py")

    base_rss = rss_mb()
    peak = base_rss
    print(f"文档：{DOC.name} {DOC.stat().st_size / 1e6:.1f}MB")
    print(f"起始内存：{base_rss:.0f}MB\n")

    # ---- 解析 ----
    t0 = time.time()
    paper = parse_pdf(DOC)
    parse_sec = time.time() - t0
    peak = max(peak, rss_mb())
    st = summary(paper)
    print(f"解析：{parse_sec:.1f}s  页 {st['pages']}  块 {st['blocks']}  "
          f"标题 {st['headings']}  文献 {st['references']}  峰值内存 {peak:.0f}MB")

    check("页数 >= 500", st["pages"] >= 500, str(st["pages"]))
    check("解析耗时 < 360s（文档承诺 ≤6 分钟）", parse_sec < MAX_PARSE_SEC, f"{parse_sec:.0f}s")
    check("峰值内存 < 2000MB", peak < MAX_PEAK_MB, f"{peak:.0f}MB")
    check("产出文本块", st["blocks"] > 1000, str(st["blocks"]))
    check("识别出标题", st["headings"] >= 20, str(st["headings"]))

    # ---- 分块 ----
    t0 = time.time()
    chunks = build_chunks(paper)
    chunk_sec = time.time() - t0
    cs = chunk_stats(chunks)
    print(f"分块：{chunk_sec:.1f}s  块数 {cs['count']}  平均 {cs['avg_chars']} 字  "
          f"最大 {cs['max_chars']} 字  节数 {cs['sections']}")
    check("分块数量 >= 800", cs["count"] >= 800, str(cs["count"]))
    check("单块不超过 1200 字", cs["max_chars"] <= MAX_CHUNK_CHARS, str(cs["max_chars"]))

    # ---- BM25（秒级可用是长文档的关键降级策略）----
    import jieba

    from app.indexing.retriever import tokenize
    from rank_bm25 import BM25Okapi

    t0 = time.time()
    corpus = [tokenize(c.text) for c in chunks]
    bm25 = BM25Okapi(corpus)
    bm25_sec = time.time() - t0
    print(f"BM25 建索引：{bm25_sec:.1f}s（{len(corpus)} 块）")
    check("BM25 建索引 < 60s", bm25_sec < 60.0, f"{bm25_sec:.0f}s")

    # ---- 检索可用性（BM25 单路，够验证"规模上去了还能查"）----
    t0 = time.time()
    scores = bm25.get_scores(tokenize("attention mechanism"))
    top = int(scores.argmax())
    query_sec = time.time() - t0
    hit = chunks[top]
    print(f"检索：{query_sec * 1000:.0f}ms  命中 p{hit.page_start} §{hit.section_title[:30]}")
    check("查询耗时 < 500ms", query_sec < 0.5, f"{query_sec * 1000:.0f}ms")
    check("命中块有页码锚点", hit.page_start >= 1 and len(hit.bbox) == 4)

    # ---- 稠密向量成本外推 ----
    from app.indexing.retriever import _dense_model

    sample = [c.text for c in chunks[:SAMPLE_EMBED]]
    t0 = time.time()
    list(_dense_model().embed(sample, batch_size=32))
    embed_sec = time.time() - t0
    per_chunk = embed_sec / max(len(sample), 1)
    extrapolated = per_chunk * cs["count"]
    print(f"稠密向量：{SAMPLE_EMBED} 块 {embed_sec:.1f}s → 全量 {cs['count']} 块约 {extrapolated:.0f}s")
    check(
        "全量向量化 < 420s",
        extrapolated < MAX_EXTRAPOLATED_EMBED_SEC,
        f"{extrapolated:.0f}s",
    )
    check("单块向量化 < 0.6s", per_chunk < 0.6, f"{per_chunk:.3f}s")

    passed = sum(1 for ok, _, _ in results if ok)
    for ok, name, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))
    print(f"\n{passed}/{len(results)} 项通过 · 解析 {parse_sec:.0f}s · 峰值内存 {peak:.0f}MB")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
