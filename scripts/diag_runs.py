"""调试：查看跨中缝的 run 到底是什么样，以及页面字符 x 分布。"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from app.parsing import layout as L  # noqa: E402


def main(pdf: str, page_no: int) -> None:
    doc = pymupdf.open(pdf)
    page = doc[page_no - 1]
    w = page.rect.width
    chars = L._collect_chars(page)
    print(f"page {page_no} width={w:.0f} chars={len(chars)}")

    # 字符 x0 直方图（按 10pt 分桶）
    buckets: Counter[int] = Counter()
    for c in chars:
        buckets[int(c.bbox.x0 // 10) * 10] += 1
    occupied = sorted(b for b, n in buckets.items() if n > 3)
    print("occupied x buckets:", occupied)

    runs = L.extract_runs(page)
    cross = [r for r in runs if r.bbox.x0 < w / 2 - 5 and r.bbox.x1 > w / 2 + 5]
    print(f"runs={len(runs)} crossing_mid={len(cross)}")
    for r in cross[:6]:
        print(f"  cross run bbox=({r.bbox.x0:.0f},{r.bbox.y0:.0f},{r.bbox.x1:.0f}) "
              f"len={len(r.text)} text={r.text[:120]!r}")

    lines = L._cluster_lines(chars)
    print(f"clustered lines={len(lines)}")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]))
