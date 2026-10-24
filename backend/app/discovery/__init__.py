"""论文发现与推荐子包。"""
from .arxiv import ArxivPaper, download_pdf, fetch, recent, search, to_bibtex
from .enrich import RepoInfo, github_lookup, openalex_lookup, reproducibility
from .recommend import (
    humanize,
    ingest,
    library_centroid,
    recommend,
    score_candidates,
)

__all__ = [
    "ArxivPaper",
    "download_pdf",
    "fetch",
    "recent",
    "search",
    "to_bibtex",
    "RepoInfo",
    "github_lookup",
    "openalex_lookup",
    "reproducibility",
    "humanize",
    "ingest",
    "library_centroid",
    "recommend",
    "score_candidates",
]
