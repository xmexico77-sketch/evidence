"""解析产物的数据模型。

设计要点：一切可溯源。Block 是溯源的原子单位，携带 page + bbox，
后续 RAG 的引用锚点、阅读器的高亮、双语联动的段落 id 全部由它派生。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class BBox:
    """PDF 页面坐标（左上原点，单位 pt），与 PyMuPDF 一致。"""

    x0: float
    y0: float
    x1: float
    y1: float

    def to_list(self) -> list[float]:
        return [round(self.x0, 2), round(self.y0, 2), round(self.x1, 2), round(self.y1, 2)]

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass(slots=True)
class Line:
    text: str
    bbox: BBox
    size: float
    bold: bool
    flags: int = 0


@dataclass(slots=True)
class Block:
    """阅读序中的一个文本块，也是溯源锚点。"""

    id: str
    page: int  # 1-based
    bbox: BBox
    text: str
    order: int  # 阅读序全局序号
    lines: list[Line] = field(default_factory=list)
    column: int = 0  # 0=左/单栏 1=右栏 -1=通栏
    is_full_width: bool = False
    # 由标题树推导
    section_path: str = ""
    section_title: str = ""
    is_heading: bool = False
    heading_level: int = 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["bbox"] = self.bbox.to_list()
        data.pop("lines", None)  # 行信息体积大，默认不落 JSON
        return data


@dataclass(slots=True)
class Heading:
    text: str
    level: int
    page: int
    bbox: BBox
    block_id: str
    number: str = ""
    path: str = ""


@dataclass(slots=True)
class Table:
    page: int
    bbox: BBox
    rows: list[list[str]]
    markdown: str = ""


@dataclass(slots=True)
class Reference:
    index: int
    text: str
    page: int
    bbox: BBox | None = None


@dataclass(slots=True)
class Citation:
    """正文中的引用标记，如 [11]，用于与参考文献双向跳转。"""

    marker: str
    ref_index: int
    block_id: str
    page: int


@dataclass(slots=True)
class PageInfo:
    page: int
    width: float
    height: float
    columns: int
    rotation: int = 0
    is_scanned: bool = False
    char_count: int = 0


@dataclass(slots=True)
class Paper:
    id: str
    filename: str
    sha256: str
    page_count: int
    title: str = ""
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    doi: str = ""
    arxiv_id: str = ""
    version: str = ""
    pages: list[PageInfo] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)
    headings: list[Heading] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self, include_blocks: bool = True) -> dict[str, Any]:
        return {
            "id": self.id,
            "filename": self.filename,
            "sha256": self.sha256,
            "page_count": self.page_count,
            "title": self.title,
            "authors": self.authors,
            "abstract": self.abstract,
            "doi": self.doi,
            "arxiv_id": self.arxiv_id,
            "version": self.version,
            "pages": [asdict(p) for p in self.pages],
            "blocks": [b.to_dict() for b in self.blocks] if include_blocks else [],
            "headings": [
                {
                    "text": h.text,
                    "level": h.level,
                    "page": h.page,
                    "bbox": h.bbox.to_list(),
                    "block_id": h.block_id,
                    "number": h.number,
                    "path": h.path,
                }
                for h in self.headings
            ],
            "tables": [
                {
                    "page": t.page,
                    "bbox": t.bbox.to_list(),
                    "rows": t.rows,
                    "markdown": t.markdown,
                }
                for t in self.tables
            ],
            "references": [
                {
                    "index": r.index,
                    "text": r.text,
                    "page": r.page,
                    "bbox": r.bbox.to_list() if r.bbox else None,
                }
                for r in self.references
            ],
            "citations": [asdict(c) for c in self.citations],
            "warnings": self.warnings,
        }
