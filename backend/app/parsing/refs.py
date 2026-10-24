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
_CITE_RE = re.compile(r"\[(\d{1,3}(?:\s*[,–-]\s*\d{1,3})*)\]")
_ARXIV_RE = re.compile(r"arXiv:\s*(\d{4}\.\d{4,5})(v\d+)?", re.I)
_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)\b")


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


def parse_references(blocks: list[Block], start: int) -> list[Reference]:
    """从参考文献标题之后抽取条目。

    现实情况分两种：编号式（每条以 [1]/1. 开头）与无编号式（按字母序排列）。
    切分必须保守——过切会把一条文献碎成三条，图谱直接失真。
    """
    refs: list[Reference] = []
    seen: dict[int, int] = {}
    for blk in blocks[start + 1 :]:
        text = blk.text.strip()
        if not text:
            continue
        if blk.is_heading and re.match(r"(?i)^(appendix|a\.|acknowledg)", text):
            break
        for marker, body in _split_entries(text):
            if not body:
                continue
            if marker:
                index = int(marker)
                if index in seen:
                    refs[seen[index]].text += " " + body
                    continue
                seen[index] = len(refs)
                refs.append(Reference(index=index, text=body, page=blk.page, bbox=blk.bbox))
            else:
                # 无编号：上一段没以句号收尾 => 是续行
                if refs and not refs[-1].text.rstrip().endswith("."):
                    refs[-1].text += " " + body
                else:
                    refs.append(
                        Reference(
                            index=len(refs) + 1, text=body, page=blk.page, bbox=blk.bbox
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
