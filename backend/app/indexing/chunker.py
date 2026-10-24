"""章节感知分块。

分块策略直接决定 RAG 的溯源质量，所以这里做三个取舍：

1. **不跨章节**。跨节合并会让锚点指向"介于两节之间"的位置，复核时无法自证。
2. **父子两级**。父块=小节（用于召回），子块=段落（用于引用与高亮）。
   DeepSeek 上下文够长，给父块能补足语境；但引用必须落到子块，否则锚点太粗。
3. **保 bbox**。每个块记录 page + bbox 并集，前端据此在 PDF 上画高亮框。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..schema import Block, Paper

MAX_CHUNK_CHARS = 900
MIN_CHUNK_CHARS = 120
# 单个文本块自身超长时必须切开。实测 507 页长文档里出现过 5173 字的单块，
# 这种块会撑爆向量模型的 512 token 上下文，也让检索精度变差。
HARD_SPLIT_CHARS = 1200
SENT_SPLIT = re.compile(r"(?<=[.!?。！？])\s+")
# 参考文献不参与问答检索（它们是"被引对象"，不是知识本身）
SKIP_SECTIONS = ("references", "bibliography", "参考文献")


@dataclass(slots=True)
class Chunk:
    id: str
    paper_id: str
    index: int
    text: str
    section_path: str
    section_title: str
    page_start: int
    page_end: int
    bbox: list[float]
    block_ids: list[str] = field(default_factory=list)

    def to_row(self) -> tuple:
        return (
            self.id,
            self.paper_id,
            self.index,
            self.text,
            self.section_path,
            self.section_title,
            self.page_start,
            self.page_end,
            ",".join(f"{v:.2f}" for v in self.bbox),
            "|".join(self.block_ids),
        )


def _is_skipped(block: Block) -> bool:
    title = (block.section_title or "").lower().strip()
    return any(s in title for s in SKIP_SECTIONS)


def _union_bbox(blocks: list[Block]) -> list[float]:
    return [
        min(b.bbox.x0 for b in blocks),
        min(b.bbox.y0 for b in blocks),
        max(b.bbox.x1 for b in blocks),
        max(b.bbox.y1 for b in blocks),
    ]


def _split_oversized(text: str, limit: int = MAX_CHUNK_CHARS) -> list[str]:
    """把超长文本按句子切成若干段，每段不超过 limit。

    只在句子边界切；单句本身超长（公式块、表格行）时按字符硬切，
    保证不会有任何一块超过 HARD_SPLIT_CHARS 的两倍。
    """
    if len(text) <= limit:
        return [text]
    out: list[str] = []
    buf = ""
    for sentence in SENT_SPLIT.split(text):
        s = sentence.strip()
        if not s:
            continue
        if len(s) > limit:
            # 单句过长：先冲掉缓冲，再硬切
            if buf:
                out.append(buf)
                buf = ""
            for i in range(0, len(s), limit):
                out.append(s[i : i + limit])
            continue
        if len(buf) + len(s) + 1 > limit:
            out.append(buf)
            buf = s
        else:
            buf = f"{buf} {s}".strip() if buf else s
    if buf:
        out.append(buf)
    return [p for p in out if p.strip()]


def build_chunks(paper: Paper) -> list[Chunk]:
    chunks: list[Chunk] = []
    buf: list[Block] = []
    buf_chars = 0
    current_section = None

    def emit(text: str, blocks: list[Block]) -> None:
        """把一段文本落成块；超过上限的再按句子切，保证硬上限。"""
        for piece in _split_oversized(text):
            if len(piece) < 20:
                continue
            idx = len(chunks)
            chunks.append(
                Chunk(
                    id=f"{paper.id}#c{idx:04d}",
                    paper_id=paper.id,
                    index=idx,
                    text=piece,
                    section_path=blocks[0].section_path,
                    section_title=blocks[0].section_title,
                    page_start=min(b.page for b in blocks),
                    page_end=max(b.page for b in blocks),
                    bbox=_union_bbox(blocks),
                    block_ids=[b.id for b in blocks],
                )
            )

    def flush() -> None:
        nonlocal buf, buf_chars
        if not buf:
            return
        text = " ".join(b.text for b in buf).strip()
        # 过短的尾块不能丢——它往往是某节的核心结论句。
        # 同节且合并后不超上限则并入上一块；否则单独成块。
        can_merge = (
            len(text) < MIN_CHUNK_CHARS
            and chunks
            and chunks[-1].section_path == buf[0].section_path
            and len(chunks[-1].text) + len(text) <= MAX_CHUNK_CHARS
        )
        if can_merge:
            prev = chunks[-1]
            prev.text = f"{prev.text} {text}".strip()
            prev.page_end = max(prev.page_end, max(b.page for b in buf))
            prev.block_ids.extend(b.id for b in buf)
            prev.bbox = [
                min(prev.bbox[0], min(b.bbox.x0 for b in buf)),
                min(prev.bbox[1], min(b.bbox.y0 for b in buf)),
                max(prev.bbox[2], max(b.bbox.x1 for b in buf)),
                max(prev.bbox[3], max(b.bbox.y1 for b in buf)),
            ]
        else:
            emit(text, buf)
        buf = []
        buf_chars = 0

    for block in paper.blocks:
        if block.is_heading and block.heading_level == 1 and current_section is not None:
            flush()
        section_changed = current_section is not None and block.section_path != current_section
        if section_changed:
            flush()
        current_section = block.section_path

        if block.is_heading or _is_skipped(block) or not block.text.strip():
            continue

        # 单块自身超长：切开后各自成块，锚点沿用该块的页与 bbox
        if len(block.text) > HARD_SPLIT_CHARS:
            flush()
            emit(block.text, [block])
            continue

        buf.append(block)
        buf_chars += len(block.text)
        if buf_chars >= MAX_CHUNK_CHARS:
            flush()

    flush()
    return chunks


def chunk_stats(chunks: list[Chunk]) -> dict:
    if not chunks:
        return {"count": 0}
    lens = sorted(len(c.text) for c in chunks)
    return {
        "count": len(chunks),
        "avg_chars": sum(lens) // len(lens),
        "min_chars": lens[0],
        "max_chars": lens[-1],
        "sections": len({c.section_path for c in chunks}),
        "pages": max(c.page_end for c in chunks),
    }
