"""诊断脚本：逐页打印分栏判定依据，用于调阈值。"""
from __future__ import annotations

import sys
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from app.parsing import layout as L  # noqa: E402


def main(pdf: str) -> None:
    doc = pymupdf.open(pdf)
    for pno in range(doc.page_count):
        page = doc[pno]
        runs = L.extract_runs(page)
        lay = L.detect_columns(page, runs)
        w = page.rect.width
        mid = w / 2
        tol = w * 0.02
        left = sum(1 for r in runs if r.bbox.x1 <= mid + tol)
        right = sum(1 for r in runs if r.bbox.x0 >= mid - tol)
        total = len(runs) or 1
        print(
            f"p{pno + 1:>2} cols={lay.columns} runs={len(runs):>3} "
            f"left={left:>3} right={right:>3} cov={(left + right) / total:.2f} "
            f"gutter={lay.gutter_x:.0f}"
        )


if __name__ == "__main__":
    main(sys.argv[1])
