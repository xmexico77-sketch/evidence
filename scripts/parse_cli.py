"""解析 CLI：对单个或多个 PDF 做结构化解析，落 JSON 并打印验收摘要。

用法：
  .venv\\Scripts\\python.exe scripts\\parse_cli.py data/pdf/1706.03762v1.pdf
  .venv\\Scripts\\python.exe scripts\\parse_cli.py data/pdf/*.pdf --quiet
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.config import PARSED_DIR  # noqa: E402
from app.parsing import parse_pdf, summary  # noqa: E402


def run_one(pdf: Path, dump: bool, verbose: bool) -> dict:
    paper = parse_pdf(pdf)
    stats = summary(paper)
    if dump:
        out = PARSED_DIR / f"{paper.id}.json"
        out.write_text(
            json.dumps(paper.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8"
        )
        stats["json"] = str(out)
    if verbose:
        print(f"\n=== {pdf.name}")
        for key, value in stats.items():
            print(f"  {key}: {value}")
        print("  --- 标题树（前 20）---")
        for h in paper.headings[:20]:
            indent = "  " * (h.level - 1)
            num = f"{h.number} " if h.number else ""
            print(f"    {indent}L{h.level} p{h.page:<2} {num}{h.text[:60]}")
        print("  --- 参考文献（前 3）---")
        for ref in paper.references[:3]:
            print(f"    [{ref.index}] {ref.text[:100]}")
        if paper.citations:
            sample = ", ".join(sorted({c.marker for c in paper.citations})[:12])
            print(f"  引用标记样例: {sample}")
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdfs", nargs="+")
    ap.add_argument("--no-dump", action="store_true", help="不写 JSON")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    results = []
    for pattern in args.pdfs:
        for pdf in sorted(Path().glob(pattern)) if "*" in pattern else [Path(pattern)]:
            if not pdf.exists():
                print(f"跳过不存在的文件: {pdf}")
                continue
            results.append(run_one(pdf, not args.no_dump, not args.quiet))

    if args.quiet or len(results) > 1:
        print(json.dumps(results, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
