"""版面分析：字符级重建文本行，判定分栏，重建阅读顺序。

实测踩出来的三个坑，也是本模块存在的理由：

1. **词间空格丢失**。LaTeX 排版的 PDF 常不写空格字符，靠坐标偏移表示词距，
   直接拼 span 文本会得到 "Theencoderiscomposedofastack"。按字符 bbox 间隙重建。
2. **跨栏粘行**。PyMuPDF 会把左右两栏同一基线的文字合并进同一个 line，
   于是"整行跨过中缝"，任何行级的分栏判定都会失效。必须降到字符级，
   在横向大间隙处切段。
3. **表格污染**。表格单元格是独立文本块，会被误判成标题，按表格 bbox 剔除。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import pymupdf

from ..schema import BBox, Block, Line, PageInfo

BOLD_FLAG = 2**4
FOOTER_SIZE_RATIO = 0.75
FULL_WIDTH_RATIO = 0.58
MIN_SIDE_RATIO = 0.15
# 字符间隙超过字号的这个比例，认为词间有空格
SPACE_GAP_RATIO = 0.18
# 字符间隙超过字号的这个比例，认为是栏/块之间的断裂
RUN_BREAK_RATIO = 1.15
# 同一块内字号跳变超过该值必须断开。
# 0.8 太严：ACL 模板同一栏里 11.0/10.0 交替（公式、上标），会被切成一行一块。
# 1.5 能容纳这种跳变，同时仍能分开正文（10pt）与标题（12pt）。
SIZE_BREAK = 1.5


@dataclass(slots=True)
class ColumnLayout:
    columns: int
    gutter_x: float
    page_width: float
    page_height: float


@dataclass(slots=True)
class Char:
    c: str
    bbox: BBox
    size: float
    bold: bool


def _is_cjk(ch: str) -> bool:
    return "\u4e00" <= ch <= "\u9fff"


def _collect_chars(page: pymupdf.Page) -> list[Char]:
    out: list[Char] = []
    raw = page.get_text("rawdict")
    for blk in raw.get("blocks", []):
        if blk.get("type") != 0:
            continue
        for line in blk.get("lines", []):
            # 竖排文字（arXiv 左侧水印、旋转页眉）会拆成单字行，污染标题树
            direction = line.get("dir", (1.0, 0.0))
            if abs(direction[1]) > 0.2 or direction[0] < 0.9:
                continue
            for span in line.get("spans", []):
                size = float(span.get("size", 0)) or 0.1
                flags = int(span.get("flags", 0))
                bold = bool(flags & BOLD_FLAG) or "bold" in span.get("font", "").lower()
                for ch in span.get("chars", []):
                    c = ch.get("c", "")
                    bx = ch.get("bbox")
                    if not c or not bx:
                        continue
                    out.append(Char(c=c, bbox=BBox(*bx), size=size, bold=bold))
    return out


def _text_from_chars(chars: list[Char]) -> str:
    if not chars:
        return ""
    out = [chars[0].c]
    prev = chars[0]
    for ch in chars[1:]:
        gap = ch.bbox.x0 - prev.bbox.x1
        if (
            gap > (ch.size or prev.size) * SPACE_GAP_RATIO
            and not prev.c.isspace()
            and not ch.c.isspace()
            and not (_is_cjk(prev.c) and _is_cjk(ch.c))
        ):
            out.append(" ")
        out.append(ch.c)
        prev = ch
    return "".join(out)


def _cluster_lines(chars: list[Char]) -> list[list[Char]]:
    """按基线聚成行。容差取字号的 0.5 倍，以容纳上下标。"""
    if not chars:
        return []
    ordered = sorted(chars, key=lambda c: (round(c.bbox.y0, 1), c.bbox.x0))
    lines: list[list[Char]] = []
    for ch in ordered:
        if lines:
            ref = lines[-1][0]
            if abs(ch.bbox.y0 - ref.bbox.y0) <= max(ch.size, ref.size) * 0.5:
                lines[-1].append(ch)
                continue
        lines.append([ch])
    for line in lines:
        line.sort(key=lambda c: c.bbox.x0)
    return lines


def _split_runs(line: list[Char]) -> list[list[Char]]:
    """在一行内按横向大间隙切段——这是拆开左右两栏的关键。"""
    runs: list[list[Char]] = []
    for ch in line:
        if runs:
            prev = runs[-1][-1]
            gap = ch.bbox.x0 - prev.bbox.x1
            if gap > max(ch.size, prev.size) * RUN_BREAK_RATIO:
                runs.append([ch])
                continue
            runs[-1].append(ch)
        else:
            runs.append([ch])
    return runs


def extract_runs(page: pymupdf.Page) -> list[Line]:
    """把页面重建为若干"单栏文本段"。每段只属于一个栏位，可安全排序。"""
    chars = _collect_chars(page)
    if not chars:
        return []

    runs: list[Line] = []
    for line_chars in _cluster_lines(chars):
        raw_runs = _split_runs(line_chars)
        # 合并上下标等碎片到相邻主段
        merged: list[list[Char]] = []
        for run in raw_runs:
            if merged:
                prev = merged[-1]
                prev_h = max(c.bbox.y1 for c in prev) - min(c.bbox.y0 for c in prev)
                run_h = max(c.bbox.y1 for c in run) - min(c.bbox.y0 for c in run)
                gap = min(c.bbox.x0 for c in run) - max(c.bbox.x1 for c in prev)
                if run_h < prev_h * 0.8 and gap < max(c.size for c in prev) * 0.5:
                    prev.extend(run)
                    continue
            merged.append(run)

        for group in merged:
            text = _text_from_chars(group)
            if not text.strip():
                continue
            bbox = BBox(
                min(c.bbox.x0 for c in group),
                min(c.bbox.y0 for c in group),
                max(c.bbox.x1 for c in group),
                max(c.bbox.y1 for c in group),
            )
            bold_chars = sum(1 for c in group if c.bold)
            runs.append(
                Line(
                    text=text,
                    bbox=bbox,
                    size=max(c.size for c in group),
                    bold=bold_chars > len(group) * 0.5,
                )
            )
    return runs


def detect_columns(page: pymupdf.Page, runs: list[Line]) -> ColumnLayout:
    width = page.rect.width
    height = page.rect.height
    if len(runs) < 8:
        return ColumnLayout(1, width / 2, width, height)

    mid = width / 2
    tol = width * 0.02
    left = [r for r in runs if r.bbox.x1 <= mid + tol]
    right = [r for r in runs if r.bbox.x0 >= mid - tol]
    total = len(runs)
    two_col = (
        len(left) / total >= MIN_SIDE_RATIO
        and len(right) / total >= MIN_SIDE_RATIO
        and (len(left) + len(right)) / total >= 0.7
    )
    if not two_col:
        return ColumnLayout(1, width / 2, width, height)

    left_edge = max((r.bbox.x1 for r in left), default=width / 2)
    right_edge = min((r.bbox.x0 for r in right), default=width / 2)
    gutter = (left_edge + right_edge) / 2 if right_edge > left_edge else width / 2
    return ColumnLayout(2, gutter, width, height)


def _is_full_width(bbox: BBox, layout: ColumnLayout) -> bool:
    if layout.columns == 1:
        return True
    if bbox.width > layout.page_width * FULL_WIDTH_RATIO:
        return True
    spans_gutter = bbox.x0 < layout.gutter_x - 4 and bbox.x1 > layout.gutter_x + 4
    return spans_gutter and bbox.width > layout.page_width * 0.35


def _join_text(parts: list[str]) -> str:
    out = ""
    for raw in parts:
        token = raw.strip()
        if not token:
            continue
        if not out:
            out = token
        elif out.endswith("-") and len(out) > 1 and out[-2].isalpha() and token[:1].islower():
            out = out[:-1] + token
        else:
            out = f"{out} {token}"
    return re.sub(r"\s+", " ", out).strip()


_NUMBERED_LINE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+\S")


def _looks_like_heading_line(line: Line) -> bool:
    text = line.text.strip()
    if not text or len(text) > 90:
        return False
    if text.endswith((".", "。", ",", ";", ":")):
        return False
    # "2018. Contextual string embeddings…" 是参考文献条目，不是章节标题
    if re.match(r"^(?:19|20)\d{2}\.\s", text):
        return False
    if _NUMBERED_LINE.match(text) and len(text.split()) <= 12:
        return True
    return line.bold and len(text.split()) <= 8


def _inside_any(bbox: BBox, zones: list[BBox]) -> bool:
    cy = (bbox.y0 + bbox.y1) / 2
    for z in zones:
        if z.x0 - 2 <= bbox.cx <= z.x1 + 2 and z.y0 - 2 <= cy <= z.y1 + 2:
            return True
    return False


MIN_BLOCK_CHARS = 36
# 这些短标题绝不能被并进上一块，否则参考文献区会整体消失
_PROTECTED_TITLES = {
    "references",
    "bibliography",
    "acknowledgments",
    "acknowledgements",
    "appendix",
    "abstract",
    "摘要",
    "参考文献",
}


def _merge_short_blocks(blocks: list[Block], min_chars: int = MIN_BLOCK_CHARS) -> list[Block]:
    """把过短的碎块并回上一块（同页同栏，且前后都不是标题行）。

    实测 ACL / ICML 模板（Longformer、CLIP）会被切成每页 60–75 块，
    接近"一行一块"：既撑大索引，又让标题树与分块噪声变多。
    这是保守的后处理——只合并"短且不该独立成块"的碎片，不动真正的段落。

    踩过的坑：早期版本没检查**当前块**是不是标题，结果把
    "References" 这种短标题并进了上一段，整篇论文的参考文献区直接消失。
    """
    out: list[Block] = []
    for blk in blocks:
        blob = blk.text.strip()
        protected = (
            blob.lower().strip(" .:") in _PROTECTED_TITLES
            or (blk.lines and _looks_like_heading_line(blk.lines[-1]))
        )
        if (
            out
            and len(blk.text) < min_chars
            and not protected
            and not blk.is_full_width
            and out[-1].page == blk.page
            and out[-1].column == blk.column
            and out[-1].lines
            and not _looks_like_heading_line(out[-1].lines[-1])
        ):
            prev = out[-1]
            prev.text = f"{prev.text} {blk.text}".strip()
            prev.bbox = BBox(
                min(prev.bbox.x0, blk.bbox.x0),
                min(prev.bbox.y0, blk.bbox.y0),
                max(prev.bbox.x1, blk.bbox.x1),
                max(prev.bbox.y1, blk.bbox.y1),
            )
            prev.lines.extend(blk.lines)
            continue
        out.append(blk)
    return out


def build_blocks(
    page: pymupdf.Page,
    page_no: int,
    layout: ColumnLayout,
    body_size: float,
    start_order: int = 0,
    table_zones: list[BBox] | None = None,
) -> list[Block]:
    runs = extract_runs(page)
    if not runs:
        return []

    body_floor = body_size * FOOTER_SIZE_RATIO
    kept: list[Line] = []
    for run in runs:
        near_edge = (
            run.bbox.y0 < layout.page_height * 0.05 or run.bbox.y1 > layout.page_height * 0.95
        )
        if run.size < body_floor and len(run.text.strip()) < 60:
            continue
        if near_edge and len(run.text.strip()) < 40:
            continue
        if table_zones and _inside_any(run.bbox, table_zones):
            continue
        kept.append(run)
    if not kept:
        kept = runs

    groups: list[list[Line]] = []
    for run in kept:
        if groups:
            prev = groups[-1][-1]
            same_col = abs(run.bbox.x0 - prev.bbox.x0) < layout.page_width * 0.08
            size_stable = abs(run.size - prev.size) <= SIZE_BREAK
            gap = run.bbox.y0 - prev.bbox.y1
            # 上一行是标题行时，除非下一行本身也是标题行，否则必须断开——
            # 否则会得到 "5.3 Optimizer We used the Adam optimizer…" 这种粘连
            if _looks_like_heading_line(prev):
                continues_heading = _looks_like_heading_line(run) and abs(run.size - prev.size) < 0.6
                if not continues_heading:
                    groups.append([run])
                    continue
                size_stable = size_stable and gap < max(prev.size, run.size) * 1.0
            if same_col and size_stable and gap < max(prev.size, run.size) * 1.3:
                groups[-1].append(run)
                continue
        groups.append([run])

    raw_blocks: list[Block] = []
    for grp in groups:
        bbox = BBox(
            min(g.bbox.x0 for g in grp),
            min(g.bbox.y0 for g in grp),
            max(g.bbox.x1 for g in grp),
            max(g.bbox.y1 for g in grp),
        )
        raw_blocks.append(
            Block(
                id="",
                page=page_no,
                bbox=bbox,
                text=_join_text([g.text for g in grp]),
                order=0,
                lines=grp,
                is_full_width=_is_full_width(bbox, layout),
            )
        )

    ordered = _reading_order(raw_blocks, layout)
    ordered = _merge_short_blocks(ordered)
    for idx, blk in enumerate(ordered):
        blk.order = start_order + idx
        blk.id = f"p{page_no}_b{idx:03d}"
        blk.column = (
            (0 if blk.bbox.cx < layout.gutter_x else 1)
            if (layout.columns == 2 and not blk.is_full_width)
            else -1
        )
    return ordered


def _reading_order(blocks: list[Block], layout: ColumnLayout) -> list[Block]:
    blocks = sorted(blocks, key=lambda b: (b.bbox.y0, b.bbox.x0))
    if layout.columns == 1:
        return blocks

    ordered: list[Block] = []
    band: list[Block] = []

    def flush() -> None:
        if not band:
            return
        left = sorted([b for b in band if b.bbox.cx < layout.gutter_x], key=lambda b: b.bbox.y0)
        right = sorted([b for b in band if b.bbox.cx >= layout.gutter_x], key=lambda b: b.bbox.y0)
        ordered.extend(left)
        ordered.extend(right)
        band.clear()

    for blk in blocks:
        if blk.is_full_width:
            flush()
            ordered.append(blk)
        else:
            band.append(blk)
    flush()
    return ordered


def page_info(page: pymupdf.Page, page_no: int, columns: int) -> PageInfo:
    text = page.get_text("text").strip()
    return PageInfo(
        page=page_no,
        width=round(page.rect.width, 2),
        height=round(page.rect.height, 2),
        columns=columns,
        rotation=page.rotation,
        is_scanned=len(text) < 100,
        char_count=len(text),
    )


def estimate_body_size_from_runs(runs: list[Line]) -> float:
    weights: dict[float, int] = {}
    for run in runs:
        key = round(run.size, 1)
        weights[key] = weights.get(key, 0) + len(run.text)
    if not weights:
        return 10.0
    return max(weights.items(), key=lambda kv: kv[1])[0]


def estimate_body_size(doc: pymupdf.Document, sample: int = 8) -> float:
    runs: list[Line] = []
    for page in doc.pages(0, min(sample, doc.page_count)):
        runs.extend(extract_runs(page))
    return estimate_body_size_from_runs(runs)


def looks_like_running_head(text: str) -> bool:
    t = text.strip()
    if not t or len(t) > 90:
        return False
    if re.fullmatch(r"(?i)arxiv:\S+.*", t):
        return True
    if re.fullmatch(r"\d{1,4}", t):
        return True
    return False
