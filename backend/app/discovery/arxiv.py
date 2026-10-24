"""arXiv 检索、元数据与下载。

礼貌策略：arXiv 官方要求请求间隔 ≥3 秒，这里做进程级节流，
避免把演示脚本跑成"被封 IP"。
"""
from __future__ import annotations

import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

API = "http://export.arxiv.org/api/query"
PDF = "https://arxiv.org/pdf/"
UA = "evidence-agent/0.1 (research assistant demo)"
MIN_INTERVAL = 3.0

NS = {
    "a": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

_last_call = 0.0


@dataclass(slots=True)
class ArxivPaper:
    id: str
    title: str
    summary: str
    authors: list[str] = field(default_factory=list)
    published: str = ""
    updated: str = ""
    categories: list[str] = field(default_factory=list)
    comment: str = ""
    journal_ref: str = ""

    @property
    def year(self) -> int:
        m = re.match(r"(\d{4})", self.published)
        return int(m.group(1)) if m else 0

    @property
    def pdf_url(self) -> str:
        return f"{PDF}{self.id}"

    def to_row(self) -> tuple:
        return (
            self.id,
            self.title,
            self.summary,
            ", ".join(self.authors),
            self.published,
            ", ".join(self.categories),
        )


def _throttle() -> None:
    global _last_call
    elapsed = time.time() - _last_call
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    _last_call = time.time()


def _get(url: str, timeout: float = 40.0) -> bytes:
    _throttle()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _parse_entry(entry: ET.Element) -> ArxivPaper:
    raw_id = entry.findtext("a:id", default="", namespaces=NS)
    m = re.search(r"abs/([^v]+)(v\d+)?$", raw_id)
    arxiv_id = m.group(1) if m else raw_id.rsplit("/", 1)[-1]
    return ArxivPaper(
        id=arxiv_id,
        title=_clean(entry.findtext("a:title", default="", namespaces=NS)),
        summary=_clean(entry.findtext("a:summary", default="", namespaces=NS)),
        authors=[
            _clean(a.findtext("a:name", default="", namespaces=NS))
            for a in entry.findall("a:author", NS)
        ],
        published=entry.findtext("a:published", default="", namespaces=NS),
        updated=entry.findtext("a:updated", default="", namespaces=NS),
        categories=[
            c.get("term", "") for c in entry.findall("a:category", NS) if c.get("term")
        ],
        comment=_clean(entry.findtext("arxiv:comment", default="", namespaces=NS)),
        journal_ref=_clean(entry.findtext("arxiv:journal_ref", default="", namespaces=NS)),
    )


def search(
    query: str,
    max_results: int = 10,
    sort_by: str = "relevance",
    sort_order: str = "descending",
) -> list[ArxivPaper]:
    """按关键词检索。query 支持 arXiv 语法，如 `cat:cs.CL`、`ti:"transformer"`。"""
    params = urllib.parse.urlencode(
        {
            "search_query": query,
            "start": 0,
            "max_results": max_results,
            "sortBy": sort_by,
            "sortOrder": sort_order,
        }
    )
    xml = _get(f"{API}?{params}")
    root = ET.fromstring(xml)
    return [_parse_entry(e) for e in root.findall("a:entry", NS)]


def fetch(arxiv_id: str) -> ArxivPaper | None:
    base = arxiv_id.split("v")[0]
    xml = _get(f"{API}?id_list={base}")
    root = ET.fromstring(xml)
    entries = root.findall("a:entry", NS)
    return _parse_entry(entries[0]) if entries else None


def recent(category: str = "cs.CL", max_results: int = 15) -> list[ArxivPaper]:
    """按提交时间倒序拉取某分类最新论文——用于"动态追踪"。"""
    return search(f"cat:{category}", max_results=max_results, sort_by="submittedDate")


def download_pdf(arxiv_id: str, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    base = arxiv_id.split("v")[0]
    target = dest_dir / f"{base}.pdf"
    if target.exists() and target.stat().st_size > 50_000:
        return target
    data = _get(f"{PDF}{base}", timeout=120)
    if len(data) < 50_000:
        raise ValueError(f"下载内容过小（{len(data)}B），可能被拦截")
    target.write_bytes(data)
    return target


def to_bibtex(paper: ArxivPaper) -> str:
    """给写作模块用：把检索结果转成可直接引用的 BibTeX。"""
    key = f"{paper.authors[0].split()[-1].lower() if paper.authors else 'anon'}{paper.year}"
    authors = " and ".join(paper.authors)
    return (
        "@misc{" + key + ",\n"
        f"  title  = {{{paper.title}}},\n"
        f"  author = {{{authors}}},\n"
        f"  year   = {{{paper.year}}},\n"
        f"  eprint = {{{paper.id}}},\n"
        "  archivePrefix = {arXiv},\n"
        "}\n"
    )
