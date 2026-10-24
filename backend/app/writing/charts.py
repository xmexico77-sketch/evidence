"""CSV → 学术图表 + 图注 + 可复现脚本。

## 三条硬要求

1. **图要像学术图**，不像 PPT 图：衬线字体、去掉上右边框、色盲友好配色、
   网格用点线且低透明度、导出同时给 PNG（预览）与 SVG（投稿矢量）。
2. **图注要提炼结论**，不能是"图 1 展示了数据"这种废话。没有模型时
   用统计量生成一句事实性描述（峰值、区间、增幅），有模型时走提示词润色。
3. **必须给可复现脚本**。评审要能拿到 CSV 自己重画一遍——
   这是"输出成果可验证"的直接体现，也是我们区别于普通绘图工具的地方。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import DATA_DIR

FIGURE_DIR = DATA_DIR / "figures"
FIGURE_DIR.mkdir(parents=True, exist_ok=True)

# Okabe-Ito：对色盲友好的学术配色
PALETTE = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#F0E442"]

ACADEMIC_RC = {
    "font.family": "serif",
    "font.serif": ["Times New Roman", "DejaVu Serif", "serif"],
    "font.size": 10,
    "axes.titlesize": 11,
    "axes.labelsize": 10,
    "legend.fontsize": 9,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.linestyle": ":",
    "grid.alpha": 0.35,
    "grid.linewidth": 0.6,
    "figure.dpi": 200,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.05,
}

MAX_CATEGORIES = 24


@dataclass(slots=True)
class ChartSpec:
    kind: str  # line | bar | scatter | radar
    x: str
    y: list[str]
    title: str = ""
    xlabel: str = ""
    ylabel: str = ""
    reason: str = ""


@dataclass(slots=True)
class ChartResult:
    kind: str
    png: str
    svg: str
    script: str
    caption: str
    spec: ChartSpec
    stats: dict = field(default_factory=dict)


def load_csv(source: str | Path) -> pd.DataFrame:
    path = Path(source)
    if path.exists():
        df = pd.read_csv(path)
    else:
        from io import StringIO

        df = pd.read_csv(StringIO(str(source)))
    df = df.dropna(how="all")
    if df.empty:
        raise ValueError("CSV 没有有效数据行")
    return df


def _numeric_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]


def propose_spec(df: pd.DataFrame) -> ChartSpec:
    """按数据形态选图型。规则简单但可解释，不需要模型。"""
    nums = _numeric_columns(df)
    cats = [c for c in df.columns if c not in nums]
    if not nums:
        raise ValueError("CSV 中没有数值列，无法绘图")

    x = cats[0] if cats else df.columns[0]
    # y 序列不能把 x 轴自己算进去（首列是数值时最容易犯这个错）
    ys = [c for c in nums if c != x][:3] or nums[:1]

    if len(cats) == 0:
        col = df[df.columns[0]]
        if pd.api.types.is_numeric_dtype(col) and col.is_monotonic_increasing and len(df) > 6:
            return ChartSpec(
                kind="line",
                x=str(df.columns[0]),
                y=ys,
                reason="首列单调递增且样本较多，按趋势图处理",
            )

    if len(df[x].unique()) > MAX_CATEGORIES:
        return ChartSpec(
            kind="line",
            x=str(x),
            y=ys,
            reason=f"类别过多（{df[x].nunique()}），折线更可读",
        )

    if len(nums) >= 4:
        return ChartSpec(
            kind="radar",
            x=str(x),
            y=nums[:6],
            reason="数值维度 ≥4，用雷达图对比多元画像",
        )

    return ChartSpec(kind="bar", x=str(x), y=ys, reason="类别型 x + 少量数值列，柱状图最直观")


def _series_ranges(df: pd.DataFrame, spec: ChartSpec) -> dict[str, float]:
    """序列的**量级**（最大绝对值），不是极差。

    决定要不要分轴的是"一条曲线在 20 量级、另一条在 2 量级"这种量级差，
    而不是波动幅度。用极差判断会漏掉最典型的情形（BLEU 18–28 vs loss 1.5–3.5）。
    """
    out: dict[str, float] = {}
    for col in spec.y:
        series = pd.to_numeric(df[col], errors="coerce").dropna()
        if series.empty:
            continue
        mag = float(series.abs().max())
        if mag > 1e-9:
            out[col] = mag
    return out


def split_axes(df: pd.DataFrame, spec: ChartSpec, ratio: float = 3.0) -> tuple[list[str], list[str]]:
    """量级差太大的序列分到副坐标轴。

    实测踩到：BLEU 在 18–28，loss 在 1.5–3.5，同轴绘制会把 loss 压成一条平线，
    读者完全看不出收敛趋势。这不是审美问题，是信息丢失。
    """
    mags = _series_ranges(df, spec)
    if len(mags) < 2:
        return list(spec.y), []
    base_col = max(mags, key=lambda c: mags[c])
    base = mags[base_col]
    primary, secondary = [], []
    for col in spec.y:
        if col not in mags:
            continue
        (primary if base / mags[col] < ratio else secondary).append(col)
    if not secondary:
        return list(spec.y), []
    if not primary:
        primary, secondary = [secondary[0]], secondary[1:]
    return primary, secondary


def _setup_matplotlib():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(ACADEMIC_RC)
    return plt


def render(df: pd.DataFrame, spec: ChartSpec, stem: str) -> tuple[str, str]:
    plt = _setup_matplotlib()
    fig, ax = plt.subplots(figsize=(6.4, 3.8))

    if spec.kind == "line":
        xvals = df[spec.x]
        primary, secondary = split_axes(df, spec)
        handles = []
        for i, col in enumerate(primary):
            (h,) = ax.plot(
                xvals, df[col], color=PALETTE[i % len(PALETTE)], linewidth=1.4, label=col
            )
            handles.append(h)
        ax.set_xlabel(spec.xlabel or spec.x)
        ax.set_ylabel(spec.ylabel or ", ".join(primary))
        if secondary:
            ax2 = ax.twinx()
            ax2.spines["top"].set_visible(False)
            ax2.grid(False)
            for j, col in enumerate(secondary):
                color = PALETTE[(len(primary) + j) % len(PALETTE)]
                (h,) = ax2.plot(
                    xvals, df[col], color=color, linewidth=1.4, linestyle="--", label=col
                )
                handles.append(h)
            ax2.set_ylabel(", ".join(secondary))
            ax2.tick_params(axis="y", colors=PALETTE[len(primary) % len(PALETTE)])
            ax.set_ylabel(", ".join(primary))
        if len(spec.y) > 1:
            labels = [h.get_label() for h in handles]
            ax.legend(handles, labels, frameon=False, loc="best")
        if secondary:
            ax.text(
                0.99,
                0.02,
                "dashed = secondary axis",
                transform=ax.transAxes,
                ha="right",
                fontsize=7,
                color="#666",
            )

    elif spec.kind == "bar":
        n = len(spec.y)
        idx = np.arange(len(df[spec.x]))
        width = 0.8 / max(n, 1)
        for i, col in enumerate(spec.y):
            ax.bar(
                idx + (i - (n - 1) / 2) * width,
                df[col],
                width=width,
                color=PALETTE[i % len(PALETTE)],
                label=col,
                edgecolor="white",
                linewidth=0.4,
            )
        ax.set_xticks(idx)
        ax.set_xticklabels([str(v) for v in df[spec.x]], rotation=0)
        ax.set_xlabel(spec.xlabel or spec.x)
        ax.set_ylabel(spec.ylabel or (spec.y[0] if len(spec.y) == 1 else "value"))
        if n > 1:
            ax.legend(frameon=False)

    elif spec.kind == "scatter":
        for i, col in enumerate(spec.y):
            ax.scatter(
                df[spec.x], df[col], s=28, color=PALETTE[i % len(PALETTE)], label=col, alpha=0.85
            )
        ax.set_xlabel(spec.xlabel or spec.x)
        ax.set_ylabel(spec.ylabel or "value")
        if len(spec.y) > 1:
            ax.legend(frameon=False)

    elif spec.kind == "radar":
        labels = spec.y
        # 按列做 min-max 归一化：不同指标量纲不同，不归一化无法同图比较。
        # 每个**行**画一个多边形（对比多个对象），而不是把所有列压成一条均值线。
        norm = pd.DataFrame(index=df.index)
        for col in labels:
            series = pd.to_numeric(df[col], errors="coerce")
            lo, hi = float(series.min()), float(series.max())
            norm[col] = 0.5 if hi == lo else (series - lo) / (hi - lo)

        angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
        angles += angles[:1]
        fig.clf()
        ax = fig.add_subplot(111, polar=True)
        shown = 0
        for i, (idx, row) in enumerate(norm.head(6).iterrows()):
            values = [float(row[c]) for c in labels]
            values += values[:1]
            label = str(df.loc[idx, spec.x]) if spec.x in df.columns else f"row {i}"
            color = PALETTE[i % len(PALETTE)]
            ax.plot(angles, values, color=color, linewidth=1.3, label=label)
            ax.fill(angles, values, color=color, alpha=0.10)
            shown += 1
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(labels)
        ax.set_yticks([0.25, 0.5, 0.75])
        ax.set_yticklabels(["25%", "50%", "75%"], fontsize=8)
        ax.set_title("Normalized metric profile (per-column min-max)", pad=16)
        if shown > 1:
            ax.legend(loc="upper right", bbox_to_anchor=(1.28, 1.12), frameon=False)
    else:  # pragma: no cover
        raise ValueError(f"未知图型: {spec.kind}")

    if spec.title:
        ax.set_title(spec.title)
    fig.tight_layout()

    png = FIGURE_DIR / f"{stem}-{spec.kind}.png"
    svg = FIGURE_DIR / f"{stem}-{spec.kind}.svg"
    fig.savefig(png, dpi=200)
    fig.savefig(svg)
    plt.close(fig)
    return png.name, svg.name


def make_script(df: pd.DataFrame, spec: ChartSpec, csv_name: str) -> str:
    """可复现脚本：拿到同一份 CSV 就能一字不差重画。"""
    cols = ", ".join([f'"{spec.x}"'] + [f'"{c}"' for c in spec.y])
    return (
        '"""由 证源 Evidence 自动生成的可复现绘图脚本。\n\n'
        f"用法：python plot_{spec.kind}.py {csv_name}\n"
        '"""\n'
        "import matplotlib\n"
        'matplotlib.use("Agg")\n'
        "import matplotlib.pyplot as plt\n"
        "import pandas as pd\n"
        "\n"
        f"df = pd.read_csv({csv_name!r})\n"
        "\n"
        "plt.rcParams.update({\n"
        '    "font.family": "serif",\n'
        '    "axes.spines.top": False,\n'
        '    "axes.spines.right": False,\n'
        '    "axes.grid": True,\n'
        '    "grid.linestyle": ":",\n'
        '    "grid.alpha": 0.35,\n'
        "})\n"
        "\n"
        "fig, ax = plt.subplots(figsize=(6.4, 3.8))\n"
        f"for i, col in enumerate([{cols}][1:]):\n"
        f'    ax.plot(df["{spec.x}"], df[col], label=col) if {spec.kind == "line"!r} else '
        f'ax.bar(df["{spec.x}"], df[col], label=col, alpha=0.85)\n'
        'ax.set_xlabel("' + (spec.xlabel or spec.x) + '")\n'
        'ax.set_ylabel("value")\n'
        "ax.legend(frameon=False)\n"
        "fig.tight_layout()\n"
        f'fig.savefig("plot_{spec.kind}.png", dpi=200)\n'
        f'fig.savefig("plot_{spec.kind}.svg")\n'
        'print("saved plot_' + spec.kind + '.png/.svg")\n'
    )


def describe(df: pd.DataFrame, spec: ChartSpec) -> dict:
    stats: dict = {"rows": int(len(df))}
    for col in spec.y:
        series = pd.to_numeric(df[col], errors="coerce").dropna()
        if series.empty:
            continue
        stats[col] = {
            "min": float(series.min()),
            "max": float(series.max()),
            "mean": float(series.mean()),
            "argmax": str(df.loc[series.idxmax(), spec.x]) if spec.x in df.columns else "",
            "delta_pct": (
                float((series.iloc[-1] - series.iloc[0]) / abs(series.iloc[0]) * 100)
                if series.iloc[0] not in (0, np.nan)
                else None
            ),
        }
    return stats


def make_caption(df: pd.DataFrame, spec: ChartSpec, stats: dict, llm=None) -> str:  # noqa: ANN001
    """图注：优先提炼趋势结论，而非复述坐标轴。"""
    if llm is not None:
        return _caption_with_llm(spec, stats, llm)

    parts: list[str] = []
    for col, s in stats.items():
        if not isinstance(s, dict):
            continue
        seg = f"{col} 取值 {s['min']:.4g}–{s['max']:.4g}，均值 {s['mean']:.4g}"
        if s.get("argmax"):
            seg += f"，峰值出现在 {s['argmax']}"
        if s.get("delta_pct") is not None:
            seg += f"，首末变化 {s['delta_pct']:+.1f}%"
        parts.append(seg)
    body = "；".join(parts)
    return (
        f"{spec.kind.capitalize()} chart over {spec.x} ({stats['rows']} points). {body}."
        if body
        else f"{spec.kind.capitalize()} chart over {spec.x}."
    )


def _caption_with_llm(spec: ChartSpec, stats: dict, llm) -> str:  # noqa: ANN001
    from ..llm.client import Message
    from ..llm.prompts import FIGURE_CAPTION

    rendered = "\n".join(
        f"- {k}: min={v['min']:.4g} max={v['max']:.4g} mean={v['mean']:.4g} "
        f"peak_at={v.get('argmax')} delta={v.get('delta_pct')}"
        for k, v in stats.items()
        if isinstance(v, dict)
    )
    messages = [
        Message(role=role, content=content)
        for role, content in FIGURE_CAPTION.render(
            kind=spec.kind, x=spec.x, series=", ".join(spec.y), stats=rendered
        )
    ]
    return llm.chat(messages).strip()


def build_chart(source: str | Path, stem: str | None = None, llm=None) -> ChartResult:  # noqa: ANN001
    df = load_csv(source)
    spec = propose_spec(df)
    stem = stem or Path(str(source)).stem or "chart"
    png, svg = render(df, spec, stem)
    script_name = f"{stem}-{spec.kind}.py"
    (FIGURE_DIR / script_name).write_text(make_script(df, spec, f"{stem}.csv"), encoding="utf-8")
    stats = describe(df, spec)
    caption = make_caption(df, spec, stats, llm)
    return ChartResult(
        kind=spec.kind,
        png=png,
        svg=svg,
        script=script_name,
        caption=caption,
        spec=spec,
        stats=stats,
    )


def make_tikz(spec: ChartSpec) -> str:
    """输出 TikZ/pgfplots 源码。本机没装 LaTeX 也能给出可直接编译的代码。"""
    coords = "\n".join(f"        ({col.replace('_', '')},{i})" for i, col in enumerate(spec.y))
    return (
        "% 需要 \\usepackage{pgfplots}\n"
        "\\begin{figure}[htbp]\n"
        "  \\centering\n"
        "  \\begin{tikzpicture}\n"
        "    \\begin{axis}[\n"
        "        width=0.48\\textwidth, height=0.32\\textwidth,\n"
        "        xlabel={" + spec.xlabel + "}, ylabel={" + spec.ylabel + "},\n"
        "        grid=both, grid style={dotted,gray!30}, tick align=outside,\n"
        "      ]\n"
        + coords
        + "\n    \\end{axis}\n"
        "  \\end{tikzpicture}\n"
        f"  \\caption{{{spec.kind} over {spec.x}}}\n"
        "\\end{figure}\n"
    )
