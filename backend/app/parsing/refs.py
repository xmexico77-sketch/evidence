"""参考文献与正文引用标记解析。

为什么要做到这一步：模块三要求"正文 [11] 与 References 条目双向无损跳转"，
模块五要用参考文献建引用图谱。两者都依赖同一份映射表：标记 -> 条目 -> bbox。
"""
from __future__ import annotations

import re

from ..schema import BBox, Block, Citation, Reference

_REF_HEADING_RE = re.compile(r"^(?:\d+\.?\s*)?(references|bibliography|参考文献)$", re.I)
_MARK_RE = re.compile(r"\[(\d{1,3})\]")
_NUM_LEAD_RE = re.compile(r"^(\d{1,3})\.\s")
# 行首标记：整行的开头才是新条目的信号。用行而不是用块，
# 因为我们的块合并会把十几条参考文献并成一块（实测 T5 只解出 10 条）。
_MARK_LINE = re.compile(r"^\s*\[(\d{1,3})\]\s*|^\s*(\d{1,3})\.\s+")
_CITE_RE = re.compile(r"\[(\d{1,3}(?:\s*[,–-]\s*\d{1,3})*)\]")
_ARXIV_RE = re.compile(r"arXiv:\s*(\d{4}\.\d{4,5})(v\d+)?", re.I)
_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)\b")
_APPENDIX_RE = re.compile(r"(?i)^(appendix|a\.\s|acknowledg)")


def find_reference_heading(blocks: list[Block]) -> int | None:
    """先按标题找；找不到就退回按文本内容找（有些 PDF 的 References 没有视觉标题特征）。"""
    for idx, blk in enumerate(blocks):
        if blk.is_heading and _REF_HEADING_RE.match(blk.text.strip().strip("*")):
            return idx
    for idx, blk in enumerate(blocks):
        text = blk.text.strip().strip("*").strip()
        if len(text) <= 24 and _REF_HEADING_RE.match(text):
            return idx
    return None


_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")


def _looks_like_citation(text: str) -> bool:
    """过滤误切：附录里的编号步骤、公式编号等不是文献。

    真实文献条目几乎必然满足其一：含四位年份、含 arXiv、含 et al、长度足够。
    """
    if len(text) < 45:
        return False
    return bool(
        _YEAR_RE.search(text)
        or "arxiv" in text.lower()
        or "et al" in text.lower()
        or "doi" in text.lower()
    )


def parse_references(blocks: list[Block], start: int) -> list[Reference]:
    """从参考文献标题之后抽取条目。

    三次踩坑后的结论：
    1. **按行切，不按块切**——块合并会把十几条并成一块（T5 曾只解出 10 条）；
    2. **遇到下一个一级标题必须停**——否则附录里的编号列表会被当成文献
       （Adam 曾解出 323 条，实际 15 条）；
    3. **条目要过"像文献"的校验**——否则公式编号、步骤列表都会进来。
    """
    lines: list[tuple[int, object]] = []
    for blk in blocks[start + 1 :]:
        if blk.is_heading and _APPENDIX_RE.match(blk.text.strip()):
            break
        lines.extend((blk.page, ln) for ln in blk.lines)

    bracket = [i for i, (_, ln) in enumerate(lines) if re.match(r"^\s*\[\d{1,3}\]", ln.text)]
    dotted = [i for i, (_, ln) in enumerate(lines) if re.match(r"^\s*\d{1,3}\.\s+\S", ln.text)]

    refs: list[Reference]
    if len(bracket) >= 3:
        refs = _parse_marked_lines(lines, bracket, bracket_style=True)
    elif len(dotted) >= 3:
        refs = _parse_marked_lines(lines, dotted, bracket_style=False)
    else:
        refs = _split_unmarked_lines(lines)

    return [r for r in refs if _looks_like_citation(r.text)]


def _parse_marked_lines(
    lines: list[tuple[int, object]], marked: list[int], bracket_style: bool = True
) -> list[Reference]:
    """按"行首标记"切分；标记之间的行并入当前条目。"""
    refs: list[Reference] = []
    seen: dict[int, int] = {}
    bounds = list(zip(marked, marked[1:] + [len(lines)], strict=False))
    for start_i, end_i in bounds:
        head_text = lines[start_i][1].text.strip()
        m = (
            re.match(r"^\s*\[(\d{1,3})\]", head_text)
            if bracket_style
            else re.match(r"^\s*(\d{1,3})\.\s+", head_text)
        )
        if not m:
            continue
        index = int(m.group(1))
        parts = [head_text[m.end() :].strip()]
        for j in range(start_i + 1, end_i):
            parts.append(lines[j][1].text.strip())
        body = re.sub(r"\s+", " ", " ".join(p for p in parts if p)).strip()
        if not body:
            continue
        page = lines[start_i][0]
        bbox = lines[start_i][1].bbox
        if index in seen:
            refs[seen[index]].text += " " + body
            continue
        seen[index] = len(refs)
        refs.append(Reference(index=index, text=body, page=page, bbox=bbox))
    return refs


_AUTHOR_START = re.compile(
    r"^(?:"
    r"[A-Z][A-Za-zÀ-ÿ\-'’]+,\s"  # 姓, 名（Springer/ICML 常见）
    r"|(?:[A-Z][A-Za-zÀ-ÿ\-'’]+\.?\s+){1,3}[A-Z][A-Za-zÀ-ÿ\-'’]+,(?:\s|$)"  # 名 姓,（ACL 常见）
    r"|[A-Z]\.(?:\s?[A-Z]\.)*\s+[A-Z][a-z]+"  # J. Smith
    r")"
)
_INITIAL_START = _AUTHOR_START


def _split_unmarked_lines(lines: list[tuple[int, object]]) -> list[Reference]:
    """作者-年份式文献表：以"姓氏," 或 "首字母. 姓" 判断新条目起点。

    这类表没有编号，只能靠作者名模式切分。实测 Adam 的文献表就属于这种，
    之前按块切会整段并成 1 条。
    """
    starts: list[int] = []
    for i, (_page, ln) in enumerate(lines):
        text = ln.text.strip()
        if not text:
            continue
        if _AUTHOR_START.match(text):
            starts.append(i)

    if not starts:
        return []

    refs: list[Reference] = []
    bounds = list(zip(starts, starts[1:] + [len(lines)], strict=False))
    for start_i, end_i in bounds:
        parts = [lines[j][1].text.strip() for j in range(start_i, end_i)]
        body = re.sub(r"\s+", " ", " ".join(p for p in parts if p)).strip()
        if not body:
            continue
        refs.append(
            Reference(
                index=len(refs) + 1,
                text=body,
                page=lines[start_i][0],
                bbox=lines[start_i][1].bbox,
            )
        )
    return refs


def _split_entries(text: str) -> list[tuple[str, str]]:
    """把一段文本切成 (编号, 内容)。只有出现 ≥2 个 [n] 标记时才切分。"""
    marks = list(_MARK_RE.finditer(text))
    if len(marks) >= 2:
        out: list[tuple[str, str]] = []
        lead = text[: marks[0].start()].strip()
        if lead:
            out.append(("", lead))
        for i, mark in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
            out.append((mark.group(1), text[mark.end() : end].strip()))
        return out
    m = _MARK_RE.match(text)
    if m:
        return [(m.group(1), text[m.end() :].strip())]
    m = _NUM_LEAD_RE.match(text)
    if m:
        return [(m.group(1), text[m.end() :].strip())]
    return [("", text)]


def parse_citations(blocks: list[Block], ref_start: int | None) -> list[Citation]:
    """抽取正文里的 [n] 标记，排除参考文献区自身。"""
    out: list[Citation] = []
    for idx, blk in enumerate(blocks):
        if ref_start is not None and idx >= ref_start:
            continue
        if blk.is_heading:
            continue
        for m in _CITE_RE.finditer(blk.text):
            for num in _expand_marker(m.group(1)):
                out.append(
                    Citation(
                        marker=m.group(0),
                        ref_index=num,
                        block_id=blk.id,
                        page=blk.page,
                    )
                )
    return out


def _expand_marker(inner: str) -> list[int]:
    nums: list[int] = []
    for part in inner.split(","):
        part = part.strip()
        if re.fullmatch(r"\d+", part):
            nums.append(int(part))
            continue
        m = re.fullmatch(r"(\d+)\s*[–-]\s*(\d+)", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if 0 < b - a <= 30:
                nums.extend(range(a, b + 1))
    return nums


def extract_identifiers(text: str) -> tuple[str, str]:
    """从首页文本里抽 arXiv id 与 DOI。"""
    arxiv = ""
    m = _ARXIV_RE.search(text)
    if m:
        arxiv = m.group(1) + (m.group(2) or "")
    doi = ""
    m = _DOI_RE.search(text)
    if m:
        doi = m.group(1).rstrip(".,;")
    return arxiv, doi


def merge_reference_bboxes(refs: list[Reference], blocks: list[Block]) -> None:
    """把条目 bbox 精确到块内位置（如果一条参考文献独占一块则直接用）。"""
    by_id = {b.id: b for b in blocks}
    for ref in refs:
        if ref.bbox is None:
            continue
        _ = by_id  # 预留：后续可按字符级 bbox 精修
