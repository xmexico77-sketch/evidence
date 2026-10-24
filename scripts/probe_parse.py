"""M1 可行性探针：验证 PyMuPDF 双栏重建与标题树抽取的原料是否齐备。

跑法：.venv\\Scripts\\python.exe scripts\\probe_parse.py
"""
from __future__ import annotations

import collections
import sys
from pathlib import Path

import pymupdf

PDF_DIR = Path(__file__).resolve().parent.parent / "data" / "pdf"


def probe(path: Path) -> None:
    doc = pymupdf.open(path)
    print(f"\n=== {path.name} | {doc.page_count} pages | encrypted={doc.is_encrypted}")

    # --- 1. 文本层完整性：判断是否扫描件 ---
    chars_per_page = []
    for p in doc:
        chars_per_page.append(len(p.get_text("text").strip()))
    avg = sum(chars_per_page) / len(chars_per_page)
    print(f"  text chars/page avg={avg:.0f} min={min(chars_per_page)} "
          f"-> {'SCANNED(needs OCR)' if avg < 100 else 'vector text layer OK'}")

    # --- 2. 双栏检测：用正文页做列分割试探 ---
    body_pages = range(min(3, doc.page_count), min(8, doc.page_count))
    for pno in body_pages:
        page = doc[pno]
        w, h = page.rect.width, page.rect.height
        spans = []
        for blk in page.get_text("dict")["blocks"]:
            if blk.get("type") != 0:
                continue
            for line in blk["lines"]:
                for sp in line["spans"]:
                    if sp["text"].strip():
                        spans.append(sp["bbox"])
        if not spans:
            continue
        left = [b for b in spans if b[2] < w * 0.5]
        right = [b for b in spans if b[0] > w * 0.5]
        spanning = [b for b in spans if b[0] < w * 0.5 < b[2]]
        print(f"  p{pno + 1}: spans={len(spans):4d} left={len(left):4d} "
              f"right={len(right):4d} spanning={len(spanning):3d} "
              f"-> {'TWO-COLUMN' if len(left) > 20 and len(right) > 20 else 'single/irregular'}")

    # --- 3. 标题树原料：字号分布 ---
    sizes = collections.Counter()
    for p in doc:
        for blk in p.get_text("dict")["blocks"]:
            if blk.get("type") != 0:
                continue
            for line in blk["lines"]:
                for sp in line["spans"]:
                    t = sp["text"].strip()
                    if t:
                        sizes[round(sp["size"], 1)] += len(t)
    top = sizes.most_common(6)
    print(f"  font sizes (size:chars) -> {top}")

    # --- 4. 标题候选：大字号行的内容 ---
    cands = []
    body_size = top[0][0] if top else 10
    for pno in range(min(doc.page_count, 12)):
        for blk in doc[pno].get_text("dict")["blocks"]:
            if blk.get("type") != 0:
                continue
            for line in blk["lines"]:
                txt = "".join(sp["text"] for sp in line["spans"]).strip()
                if not txt:
                    continue
                mx = max(sp["size"] for sp in line["spans"])
                if mx > body_size + 1.5 and len(txt) < 80:
                    cands.append((pno + 1, round(mx, 1), txt))
    print(f"  heading candidates: {len(cands)} (body_size={body_size})")
    for c in cands[:14]:
        print(f"    p{c[0]:>2} [{c[1]:>4}] {c[2][:70]}")

    # --- 5. 表格 ---
    tbl_total = 0
    for pno in range(min(doc.page_count, 12)):
        try:
            tbl_total += len(doc[pno].find_tables().tables)
        except Exception as exc:  # noqa: BLE001
            print(f"  table probe p{pno + 1} failed: {exc}")
    print(f"  tables found in first 12 pages: {tbl_total}")


def probe_markdown(path: Path) -> None:
    import pymupdf4llm

    md = pymupdf4llm.to_markdown(str(path), pages=list(range(3, 7)))
    heads = [ln for ln in md.splitlines() if ln.strip().startswith("#")]
    print(f"\n  --- pymupdf4llm markdown on p4-7: {len(md)} chars, {len(heads)} headings")
    for h in heads[:10]:
        print(f"      {h[:80]}")


if __name__ == "__main__":
    targets = [PDF_DIR / "1706.03762v1.pdf", PDF_DIR / "1706.03762v7.pdf"]
    targets = [t for t in targets if t.exists()]
    if not targets:
        sys.exit(f"no PDFs in {PDF_DIR}")
    for t in targets:
        probe(t)
    probe_markdown(targets[0])
