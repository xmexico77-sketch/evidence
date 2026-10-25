"""准备长文档测试素材。

优先拿《Understanding Deep Learning》真书；拿不到就用现有 PDF 拼接出
同等规模（≥500 页）的合成长文档。合成件同样能压出内存、索引耗时、
分块策略的问题——规模才是这一项要测的东西。

用法：.venv\\Scripts\\python.exe scripts/fetch_longdoc.py
"""
from __future__ import annotations

import re
import sys
import urllib.request
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
PDF_DIR = ROOT / "data" / "pdf"
LONG_DIR = ROOT / "data" / "longdoc"
TARGET = LONG_DIR / "longdoc.pdf"
MIN_PAGES = 500

CANDIDATE_PAGES = [
    "https://github.com/udlbook/udlbook/releases",
    "https://udlbook.github.io/udlbook/",
]


def _get(url: str, timeout: float = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def try_real_book() -> Path | None:
    for page in CANDIDATE_PAGES:
        try:
            html = _get(page).decode("utf-8", "ignore")
        except Exception as exc:  # noqa: BLE001
            print(f"  页面不可达 {page}: {type(exc).__name__}")
            continue
        pdfs = set(re.findall(r'href="([^"]*\.pdf)"', html))
        # 优先名字里带 UnderstandingDeepLearning 的
        ordered = sorted(pdfs, key=lambda u: ("understanding" not in u.lower(), u))
        for link in ordered[:5]:
            url = link if link.startswith("http") else "https://github.com" + link
            try:
                data = _get(url, timeout=300)
            except Exception as exc:  # noqa: BLE001
                print(f"  下载失败 {url[:80]}: {type(exc).__name__}")
                continue
            if len(data) < 5_000_000:
                continue
            out = PDF_DIR / "udlbook.pdf"
            out.write_bytes(data)
            print(f"  已下载真书 {out.name} {len(data) / 1e6:.1f}MB")
            return out
    return None


def synth_longdoc() -> Path:
    """把现有 PDF 循环拼接，直到超过 MIN_PAGES 页。"""
    sources = sorted(p for p in PDF_DIR.glob("*.pdf") if p.name != TARGET.name)
    if not sources:
        raise SystemExit("data/pdf 下没有可用的源 PDF")

    out = pymupdf.open()
    total = 0
    rounds = 0
    while total < MIN_PAGES and rounds < 60:
        for src in sources:
            with pymupdf.open(src) as doc:
                out.insert_pdf(doc)
                total += doc.page_count
            if total >= MIN_PAGES:
                break
        rounds += 1

    out.save(TARGET, garbage=3, deflate=True)
    out.close()
    print(f"  已合成 {TARGET.name}：{total} 页，{TARGET.stat().st_size / 1e6:.1f}MB（{rounds} 轮）")
    return TARGET


def main() -> int:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    LONG_DIR.mkdir(parents=True, exist_ok=True)
    if TARGET.exists():
        with pymupdf.open(TARGET) as doc:
            if doc.page_count >= MIN_PAGES:
                print(f"已存在 {TARGET.name}（{doc.page_count} 页），跳过")
                return 0

    print("尝试获取真书…")
    book = try_real_book()
    if book is not None:
        with pymupdf.open(book) as doc:
            pages = doc.page_count
        if pages >= MIN_PAGES:
            print(f"真书 {pages} 页，直接作为长文档测试件")
            book.replace(TARGET)
            return 0
        print(f"真书只有 {pages} 页，另合成一份")

    print("合成同等规模长文档…")
    synth_longdoc()
    return 0


if __name__ == "__main__":
    sys.exit(main())
