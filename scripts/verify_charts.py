"""模块六·数据可视化验收。

关注点不只是"能出图"，而是：图型选得对、量纲差会分轴、图注含真实数字、
脚本可复现、TikZ 源码可用。

用法：.venv\\Scripts\\python.exe scripts\\verify_charts.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.writing.charts import (  # noqa: E402
    FIGURE_DIR,
    build_chart,
    load_csv,
    make_tikz,
    propose_spec,
    split_axes,
)

results: list[tuple[bool, str, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((cond, name, detail))


WIDE_CSV = """model,accuracy,latency_ms,params_m,memory_mb,bleu
base,0.81,42,110,512,27.1
large,0.86,88,340,1240,28.9
xl,0.88,150,760,2480,29.4
"""


def main() -> int:
    sample = ROOT / "data" / "samples" / "training_curves.csv"
    check("示例 CSV 存在", sample.exists(), str(sample))

    df = load_csv(sample)
    spec = propose_spec(df)
    check("选出折线图", spec.kind == "line", spec.kind)
    check("y 序列不含横轴", "epoch" not in spec.y, str(spec.y))

    primary, secondary = split_axes(df, spec)
    check("量级差异触发分轴", len(secondary) >= 1, f"primary={primary} secondary={secondary}")
    check("BLEU 留在主轴", "bleu" in primary, str(primary))
    check("损失序列进副轴", "train_loss" in secondary, str(secondary))

    result = build_chart(sample, stem="verify_charts")
    png = FIGURE_DIR / result.png
    svg = FIGURE_DIR / result.svg
    script = FIGURE_DIR / result.script
    check("PNG 已生成", png.exists() and png.stat().st_size > 10_000, str(png))
    check("SVG 已生成", svg.exists() and svg.stat().st_size > 2_000, str(svg))
    check("脚本已生成", script.exists())
    body = script.read_text(encoding="utf-8") if script.exists() else ""
    check("脚本含读取 CSV", "pd.read_csv" in body)
    check("脚本使用衬线字体", "serif" in body)

    cap = result.caption
    check("图注含列名", "bleu" in cap.lower() or "train_loss" in cap.lower(), cap[:80])
    check("图注含真实数字", any(ch.isdigit() for ch in cap), cap[:80])
    check("图注不复述空话", "this figure shows" not in cap.lower(), cap[:80])

    stats = result.stats
    check("统计量含行数", stats.get("rows") == len(df), str(stats.get("rows")))
    check(
        "统计量含首末变化",
        isinstance(stats.get("bleu"), dict) and "delta_pct" in stats["bleu"],
    )

    # 宽表 -> 雷达图
    wide_path = FIGURE_DIR / "verify_wide.csv"
    wide_path.write_text(WIDE_CSV, encoding="utf-8")
    wide = build_chart(wide_path, stem="verify_wide")
    check("宽表选出雷达图", wide.kind == "radar", wide.kind)
    check("雷达图已生成", (FIGURE_DIR / wide.png).exists())

    tikz = make_tikz(spec)
    check("TikZ 含 pgfplots", "pgfplots" in tikz and "\\begin{axis}" in tikz)

    passed = sum(1 for ok, _, _ in results if ok)
    for ok, name, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))
    print(f"\n{passed}/{len(results)} 项通过 · 图型={result.kind} · 主轴={'/'.join(primary)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
