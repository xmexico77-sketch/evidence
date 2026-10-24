"""PDF 解析编排器：把版面、标题、表格、参考文献组装成一份可溯源的 Paper。"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pymupdf

from ..schema import BBox, Paper, Table
from . import headings as H
from . import layout as L
from . import refs as R


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _markdown_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    norm = [list(r) + [""] * (width - len(r)) for r in rows]
    header = "| " + " | ".join(c.replace("|", "\\|") for c in norm[0]) + " |"
    sep = "| " + " | ".join("---" for _ in range(width)) + " |"
    body = [
        "| " + " | ".join(c.replace("|", "\\|").replace("\n", " ") for c in row) + " |"
        for row in norm[1:]
    ]
    return "\n".join([header, sep, *body])


def extract_tables(page: pymupdf.Page, page_no: int) -> list[Table]:
    out: list[Table] = []
    try:
        found = page.find_tables()
    except Exception:  # noqa: BLE001 —— 表格检测失败不应中断整篇解析
        return out
    for tbl in found.tables:
        try:
            rows = [[(c or "").strip() for c in row] for row in tbl.extract()]
        except Exception:  # noqa: BLE001
            continue
        if not rows or all(not any(cell for cell in row) for row in rows):
            continue
        x0, y0, x1, y1 = tbl.bbox
        out.append(
            Table(
                page=page_no,
                bbox=BBox(x0, y0, x1, y1),
                rows=rows,
                markdown=_markdown_table(rows),
            )
        )
    return out


def _guess_title(paper: Paper, first_page_blocks: list) -> tuple[str, list[str]]:
    """标题=首页字号最大的正文块，但要排除 arXiv 水印/版权声明这类噪声。"""
    candidates = [
        b
        for b in first_page_blocks
        if b.lines
        and b.lines[0].size >= 14
        and 6 <= len(b.text.strip()) <= 220
        and not re.search(r"(?i)arxiv|doi|proceedings|copyright|license|provided proper", b.text)
    ]
    if not candidates:
        return "", []
    biggest = max(candidates, key=lambda b: (b.lines[0].size if b.lines else 0))
    title = biggest.text.strip()
    authors: list[str] = []
    idx = first_page_blocks.index(biggest)
    for blk in first_page_blocks[idx + 1 : idx + 3]:
        t = blk.text.strip()
        if not t or re.match(r"(?i)^abstract", t):
            break
        if "†" in t or "@" in t or re.search(r"[A-Z][a-z]+ [A-Z][a-z]+", t):
            authors.append(t)
    return title, authors


def _guess_abstract(blocks: list, headings: list[H.Heading]) -> str:
    for i, h in enumerate(headings):
        if h.text.strip().lower() in {"abstract", "摘要"}:
            start = next((k for k, b in enumerate(blocks) if b.id == h.block_id), None)
            if start is None:
                continue
            buf: list[str] = []
            for blk in blocks[start + 1 :]:
                if blk.is_heading:
                    break
                buf.append(blk.text)
            return " ".join(buf).strip()
    return ""


def parse_pdf(path: str | Path, paper_id: str | None = None) -> Paper:
    path = Path(path)
    doc = pymupdf.open(path)
    body_size = L.estimate_body_size(doc)

    paper = Paper(
        id=paper_id or path.stem,
        filename=path.name,
        sha256=sha256_of(path),
        page_count=doc.page_count,
    )

    all_blocks: list = []
    first_page_blocks: list = []
    order = 0

    for pno in range(doc.page_count):
        page = doc[pno]
        runs = L.extract_runs(page)
        layout = L.detect_columns(page, runs)
        info = L.page_info(page, pno + 1, layout.columns)
        info.rotation = page.rotation
        paper.pages.append(info)
        if info.is_scanned:
            paper.warnings.append(f"p{pno + 1} 无文本层，需 OCR 兜底")
            continue

        # 先取表格 bbox，再建文本块，避免表内单元格被当成标题
        page_tables = extract_tables(page, pno + 1)
        paper.tables.extend(page_tables)
        zones = [t.bbox for t in page_tables]

        blocks = L.build_blocks(
            page, pno + 1, layout, body_size, start_order=order, table_zones=zones
        )
        order += len(blocks)
        blocks = [b for b in blocks if not L.looks_like_running_head(b.text) or b.is_heading]
        for blk in blocks:
            blk.order = len(all_blocks)
            # 块 id 必须全局唯一：只带页码和序号会在不同论文之间撞主键
            blk.id = f"{paper.id}#b{len(all_blocks):05d}"
            all_blocks.append(blk)
            if pno == 0:
                first_page_blocks.append(blk)

    paper.blocks = all_blocks
    paper.headings = H.find_headings(all_blocks, body_size)
    H.assign_sections(all_blocks, paper.headings)

    ref_start = R.find_reference_heading(all_blocks)
    if ref_start is not None:
        paper.references = R.parse_references(all_blocks, ref_start)
        paper.citations = R.parse_citations(all_blocks, ref_start)
        missing = {c.ref_index for c in paper.citations} - {r.index for r in paper.references}
        if missing:
            paper.warnings.append(f"正文引用了不存在的参考文献编号: {sorted(missing)[:10]}")
        # 编号式引用为空时，尝试作者-年份式（ACL/ICML/NeurIPS 模板）
        if not paper.citations:
            paper.citations = R.parse_author_year_citations(
                all_blocks, paper.references, ref_start
            )
            if paper.citations:
                paper.warnings.append(
                    f"该论文使用作者-年份式引用，已解析 {len(paper.citations)} 处"
                )
    else:
        paper.warnings.append("未定位到 References 章节")

    paper.title, paper.authors = _guess_title(paper, first_page_blocks)
    if not paper.title:
        meta_title = (doc.metadata or {}).get("title", "") or ""
        paper.title = meta_title.strip()
    paper.abstract = _guess_abstract(all_blocks, paper.headings)

    head_text = doc[0].get_text("text") if doc.page_count else ""
    paper.arxiv_id, paper.doi = R.extract_identifiers(head_text)
    m = re.search(r"(v\d+)$", paper.arxiv_id)
    paper.version = m.group(1) if m else ""

    doc.close()
    return paper


def summary(paper: Paper) -> dict:
    """给 CLI/接口用的紧凑统计。"""
    levels = {1: 0, 2: 0, 3: 0}
    for h in paper.headings:
        levels[h.level] = levels.get(h.level, 0) + 1
    col_pages = sum(1 for p in paper.pages if p.columns == 2)
    return {
        "id": paper.id,
        "title": paper.title,
        "arxiv": paper.arxiv_id,
        "pages": paper.page_count,
        "two_column_pages": col_pages,
        "blocks": len(paper.blocks),
        "headings": len(paper.headings),
        "heading_levels": levels,
        "tables": len(paper.tables),
        "references": len(paper.references),
        "citations": len(paper.citations),
        "abstract_chars": len(paper.abstract),
        "warnings": paper.warnings,
    }
