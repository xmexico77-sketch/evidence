"""CSV → 学术图表 CLI。

用法：
  .venv\\Scripts\\python.exe scripts\\chart_cli.py data/samples/training_curves.csv
  .venv\\Scripts\\python.exe scripts\\chart_cli.py data/samples/training_curves.csv --tikz
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.writing import build_chart, make_tikz  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--tikz", action="store_true", help="额外输出 TikZ 源码")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    result = build_chart(args.csv)
    print(f"图型：{result.kind}（{result.spec.reason}）")
    print(f"横轴：{result.spec.x}  序列：{', '.join(result.spec.y)}")
    print(f"PNG：data/figures/{result.png}")
    print(f"SVG：data/figures/{result.svg}")
    print(f"脚本：data/figures/{result.script}")
    print(f"图注：{result.caption}")

    if args.tikz:
        print("\n--- TikZ ---")
        print(make_tikz(result.spec))

    if args.json:
        print(
            json.dumps(
                {
                    "kind": result.kind,
                    "png": result.png,
                    "svg": result.svg,
                    "script": result.script,
                    "caption": result.caption,
                    "stats": result.stats,
                },
                ensure_ascii=False,
                indent=1,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
