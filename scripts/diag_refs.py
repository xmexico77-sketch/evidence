"""诊断：打印某篇论文参考文献标题之后的行，判断切分为什么失效。

用法：.venv\\Scripts\\python.exe scripts/diag_refs.py data/pdf/1412.6980.pdf
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.parsing import layout as L  # noqa: E402
from app.parsing import refs as R  # noqa: E402
from app.parsing.headings import assign_sections, find_headings  # noqa: E402
from app.parsing.pdf_parser import parse_pdf  # noqa: E402


def main(pdf: str) -> int:
    paper = parse_pdf(Path(pdf) if Path(pdf).is_absolute() else ROOT / pdf)
    idx = R.find_reference_heading(paper.blocks)
    print(f"{paper.id}: blocks={len(paper.blocks)} refs={len(paper.references)} ref_head={idx}")
    if idx is None:
        return 1
    head = paper.blocks[idx]
    print(f"标题块: {head.text!r} level={head.heading_level} p{head.page}")

    shown = 0
    for blk in paper.blocks[idx + 1 :]:
        if blk.is_heading and blk.heading_level == 1:
            print(f"  [中断] 一级标题: {blk.text[:60]!r}")
            break
        for ln in blk.lines:
            text = ln.text.strip()
            if not text:
                continue
            ok = bool(R._looks_like_citation(text))
            mark = "B" if text.startswith("[") else ("D" if text[:2].strip().rstrip('.').isdigit() else " ")
            print(f"  {mark} citeable={int(ok)} | {text[:100]}")
            shown += 1
            if shown >= 30:
                return 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
