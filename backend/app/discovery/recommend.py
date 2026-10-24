"""个性化推荐：把 arXiv 新论文与本地文献库对齐。

排序不是"谁被引得多"，而是三件事的加权：

    score = 0.60 × 与库的语义相关性
          + 0.25 × 可复现性（有无开源实现、是否官方）
          + 0.15 × 方向偏好（用户点赞过的分类）

相关性用稠密向量与"库质心"的余弦——用户读了什么，就推什么方向。
可复现性来自 GitHub 检索，这是赛题明确要求的"优先推荐附带开源代码"。
点赞/踩只调整方向偏好，不直接改相关性分，避免一两次点赞把排序带偏。
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import numpy as np

from ..indexing.retriever import _dense_model
from . import arxiv as A
from . import enrich as E

W_RELEVANCE = 0.60
W_REPRO = 0.25
W_PREF = 0.15


def library_centroid(store) -> np.ndarray | None:  # noqa: ANN001
    """库内所有块的向量均值 = 用户研究方向的粗略画像。"""
    ids, mat = store.load_vectors()
    if mat.size == 0:
        return None
    centroid = mat.mean(axis=0)
    norm = np.linalg.norm(centroid)
    return centroid / norm if norm else None


def _embed(text: str) -> np.ndarray:
    vec = np.asarray(next(iter(_dense_model().embed([text]))), dtype=np.float32)
    norm = np.linalg.norm(vec)
    return vec / norm if norm else vec


def library_arxiv_ids(store) -> set[str]:  # noqa: ANN001
    return {
        (p.get("arxiv_id") or "").split("v")[0]
        for p in store.list_papers()
        if p.get("arxiv_id")
    }


def _category_preference(store) -> dict[str, float]:  # noqa: ANN001
    """从点赞记录里统计方向偏好（占比）。"""
    feedback = store.load_feedback()
    if not feedback:
        return {}
    liked = {k for k, v in feedback.items() if v > 0}
    if not liked:
        return {}
    counts: dict[str, int] = {}
    total = 0
    for item in store.list_discoveries(limit=500):
        if item["id"] not in liked:
            continue
        for cat in (item.get("categories") or "").split(","):
            cat = cat.strip()
            if not cat:
                continue
            counts[cat] = counts.get(cat, 0) + 1
            total += 1
    return {k: v / total for k, v in counts.items()} if total else {}


def score_candidates(
    candidates: list[A.ArxivPaper],
    store,  # noqa: ANN001
    centroid: np.ndarray | None,
    pref: dict[str, float],
    enrich: bool = True,
) -> list[dict]:
    known = library_arxiv_ids(store)
    out: list[dict] = []
    for paper in candidates:
        if paper.id.split("v")[0] in known:
            continue  # 已在库中，不再推荐

        relevance = 0.0
        if centroid is not None and paper.summary:
            relevance = float(max(_embed(f"{paper.title}. {paper.summary}") @ centroid, 0.0))

        repo = E.github_lookup(paper.title, paper.id) if enrich else None
        repro_score, repro_text = E.reproducibility(repo)
        meta = E.openalex_lookup(paper.title, paper.id) if enrich else None

        pref_bonus = 0.0
        if pref and paper.categories:
            pref_bonus = max((pref.get(c, 0.0) for c in paper.categories), default=0.0)

        score = W_RELEVANCE * relevance + W_REPRO * repro_score + W_PREF * pref_bonus

        reasons = [f"与文献库方向相近度 {relevance:.2f}"]
        reasons.append(repro_text)
        if pref_bonus > 0:
            reasons.append("与你点赞过的方向一致")
        if meta and meta.get("cited_by"):
            reasons.append(f"OpenAlex 引用 {meta['cited_by']}")

        out.append(
            {
                "id": paper.id,
                "title": paper.title,
                "summary": paper.summary,
                "authors": ", ".join(paper.authors[:4]),
                "published": paper.published[:10],
                "year": paper.year,
                "categories": ", ".join(paper.categories),
                "relevance": round(relevance, 4),
                "reproducibility": round(repro_score, 3),
                "score": round(score, 4),
                "reason": "；".join(reasons),
                "repo": repo.url if repo else "",
                "repo_stars": repo.stars if repo else 0,
                "cited_by": (meta or {}).get("cited_by", 0),
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        )

    out.sort(key=lambda d: d["score"], reverse=True)
    return out


def recommend(
    store,  # noqa: ANN001
    query: str | None = None,
    category: str = "cs.CL",
    limit: int = 8,
    candidates: int = 12,
    enrich: bool = True,
) -> list[dict]:
    """query 为空时按分类拉最新论文（追踪），否则按关键词检索。"""
    papers = (
        A.search(query, max_results=candidates, sort_by="relevance")
        if query
        else A.recent(category, max_results=candidates)
    )
    centroid = library_centroid(store)
    pref = _category_preference(store)
    ranked = score_candidates(papers, store, centroid, pref, enrich=enrich)
    return ranked[:limit]


def ingest(store, paper: A.ArxivPaper, pdf_dir, build_chunks, parse_pdf) -> dict:  # noqa: ANN001
    """智能下钻：下载 PDF -> 解析 -> 分块 -> 入库。"""
    path = A.download_pdf(paper.id, pdf_dir)
    parsed = parse_pdf(path)
    chunks = build_chunks(parsed)
    store.upsert_paper(parsed, chunks)
    return {"paper_id": parsed.id, "chunks": len(chunks), "path": str(path)}


def humanize(papers: list[dict]) -> str:
    lines = []
    for i, p in enumerate(papers, 1):
        lines.append(
            f"[{i}] {p['title'][:76]}\n"
            f"    {p['published']} · {p['categories'][:48]}\n"
            f"    score={p['score']:.3f} (rel={p['relevance']:.2f} repro={p['reproducibility']:.2f})"
            f" · {p['reason']}"
        )
    return "\n".join(lines) if lines else "（无推荐结果）"


def days_since(published: str) -> int:
    try:
        dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
    except ValueError:
        return 0
    return int((datetime.now(timezone.utc) - dt).total_seconds() // 86400)


def now_stamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
