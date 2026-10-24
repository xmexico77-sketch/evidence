"""标题树识别。

论文的层级结构有两种互相印证的信源：
  1. 字号/字重（视觉层级）
  2. 编号（"3.2.1" 这种语义层级）
两者都不可靠：字号受排版影响，编号在部分论文里缺失。所以取交集——
有编号以编号定级，无编号回退到字号排名。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..schema import Block, Heading

_NUMBER_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(.*)$")
_BARE_NUMBER_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?$")
_SPECIAL_HEADS = {
    "abstract",
    "introduction",
    "conclusion",
    "conclusions",
    "references",
    "bibliography",
    "acknowledgements",
    "acknowledgments",
    "appendix",
    "related work",
    "discussion",
}
_TERMINAL = tuple(".!?,;")


@dataclass(slots=True)
class HeadingCandidate:
    block: Block
    size: float
    number: str
    title: str


def _block_size(block: Block) -> float:
    if not block.lines:
        return 0.0
    return max(ln.size for ln in block.lines)


def _block_bold_ratio(block: Block) -> float:
    if not block.lines:
        return 0.0
    bold_chars = sum(len(ln.text) for ln in block.lines if ln.bold)
    total = sum(len(ln.text) for ln in block.lines) or 1
    return bold_chars / total


_NUMERIC_JUNK = re.compile(r"^[\d\s.,·×+\-–%/()]+$")


def _is_heading_like(block: Block, body_size: float) -> bool:
    text = block.text.strip()
    if not text or len(text) > 120:
        return False
    if re.search(r"\[\s*cs\.[A-Z]+\s*\]", text):
        return False
    if len(text.split()) > 16:
        return False
    # 标题必须像"标题"：至少两个字母/汉字，且不是纯数字或表格式数值
    letters = re.findall(r"[A-Za-z\u4e00-\u9fff]", text)
    if len(letters) < 2:
        return False
    if _NUMERIC_JUNK.match(text):
        return False
    # 形如 "23.75 · 1020" 的表格数值行
    if re.match(r"^\d+(?:\.\d+)?\s*[·×]\s*\d", text):
        return False
    size = _block_size(block)
    bigger = size >= body_size * 1.06
    numbered = bool(_BARE_NUMBER_RE.match(text) or _NUMBER_RE.match(text))
    special = text.lower().strip(" .:") in _SPECIAL_HEADS
    bold_only = _block_bold_ratio(block) > 0.8 and size >= body_size and len(text) < 60
    ends_sentence = text.rstrip().endswith(_TERMINAL)
    if numbered:
        return True
    if (bigger or special) and not ends_sentence:
        return True
    return bold_only and not ends_sentence and len(text.split()) <= 10


def find_headings(blocks: list[Block], body_size: float) -> list[Heading]:
    candidates: list[HeadingCandidate] = []
    for blk in blocks:
        if not _is_heading_like(blk, body_size):
            continue
        text = blk.text.strip().strip("*").strip()
        number, title = "", text
        m = _NUMBER_RE.match(text)
        if m:
            number, title = m.group(1), m.group(2).strip()
        elif _BARE_NUMBER_RE.match(text):
            number, title = text.rstrip("."), ""
        candidates.append(
            HeadingCandidate(block=blk, size=_block_size(blk), number=number, title=title)
        )

    # 合并被排版拆散的「编号」与「标题」两个块：1 / Introduction
    merged: list[HeadingCandidate] = []
    for cand in candidates:
        if (
            merged
            and not cand.title
            and merged[-1].number
            and abs(merged[-1].size - cand.size) < 0.6
            and abs(cand.block.order - merged[-1].block.order) <= 1
            and merged[-1].block.page == cand.block.page
        ):
            merged[-1].title = ""
            continue
        if (
            merged
            and merged[-1].title == ""
            and merged[-1].number
            and abs(merged[-1].size - cand.size) < 0.6
            and 0 < cand.block.order - merged[-1].block.order <= 2
            and merged[-1].block.page == cand.block.page
        ):
            merged[-1].title = cand.title or cand.number
            merged[-1].block = cand.block
            continue
        merged.append(cand)

    # 字号排名：用于没有编号的标题定级
    sizes = sorted({round(c.size, 1) for c in merged}, reverse=True)
    size_rank = {s: i + 1 for i, s in enumerate(sizes)}

    headings: list[Heading] = []
    for cand in merged:
        if not cand.title and not cand.number:
            continue
        if cand.number:
            level = min(cand.number.count(".") + 1, 3)
        elif cand.title.lower().strip(" .:") in _SPECIAL_HEADS:
            level = 1
        else:
            level = min(size_rank.get(round(cand.size, 1), 2), 3)
        headings.append(
            Heading(
                text=cand.title or cand.number,
                level=level,
                page=cand.block.page,
                bbox=cand.block.bbox,
                block_id=cand.block.id,
                number=cand.number,
            )
        )
    return headings


def assign_sections(blocks: list[Block], headings: list[Heading]) -> None:
    """把每个块挂到最近的祖先标题上，写入 section_path / section_title。"""
    by_block = {h.block_id: h for h in headings}
    heading_ids = {h.block_id for h in headings}
    stack: list[Heading] = []

    for blk in blocks:
        head = by_block.get(blk.id)
        if head is not None:
            while stack and stack[-1].level >= head.level:
                stack.pop()
            stack.append(head)
            parts = [f"{h.number} {h.text}".strip() if h.number else h.text for h in stack]
            head.path = " > ".join(parts)
            blk.is_heading = True
            blk.heading_level = head.level
            blk.section_path = head.path
            blk.section_title = head.text
            continue

        parts = [f"{h.number} {h.text}".strip() if h.number else h.text for h in stack]
        blk.section_path = " > ".join(parts)
        blk.section_title = stack[-1].text if stack else ""

    # 回填标题自身的 path
    for h in headings:
        blk = next((b for b in blocks if b.id == h.block_id), None)
        if blk is not None:
            h.path = blk.section_path
