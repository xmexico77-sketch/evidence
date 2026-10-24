"""外部元数据补全：GitHub 开源实现 + OpenAlex 引用数。

为什么必须做"可复现性"这一层：赛题原话是"优先推荐附带开源 GitHub 代码
（易复现）的论文"。一个没有实现的新方法，对科研用户的实际价值远低于
有官方代码的同类工作——推荐排序里必须体现这个差异。
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

UA = "evidence-agent/0.1"
GH_SEARCH = "https://api.github.com/search/repositories"
OPENALEX = "https://api.openalex.org/works"

_MIN_GAP = 6.0  # GitHub 未认证搜索限速 10 次/分钟，留余量
_last_gh = 0.0
_cache: dict[str, dict] = {}


@dataclass(slots=True)
class RepoInfo:
    full_name: str
    stars: int
    url: str
    description: str = ""
    updated: str = ""
    language: str = ""

    @property
    def is_official(self) -> bool:
        text = f"{self.full_name} {self.description}".lower()
        return "official" in text


def _get(url: str, timeout: float = 25.0) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "ignore"))


def github_lookup(title: str, arxiv_id: str = "") -> RepoInfo | None:
    """按论文标题找开源实现；优先返回官方仓库，其次星数最高者。"""
    global _last_gh
    key = f"gh:{arxiv_id or title[:80]}"
    if key in _cache:
        return _cache[key].get("repo")

    elapsed = time.time() - _last_gh
    if elapsed < _MIN_GAP:
        time.sleep(_MIN_GAP - elapsed)
    _last_gh = time.time()

    # 标题里去掉标点，GitHub 搜索对符号敏感
    cleaned = re.sub(r"[^\w\s-]", " ", title).strip()
    words = " ".join(cleaned.split()[:12])
    try:
        data = _get(f"{GH_SEARCH}?q={urllib.parse.quote(words)}+in:name,description&sort=stars&per_page=5")
    except Exception:  # noqa: BLE001 —— 外部服务异常不应阻断推荐
        _cache[key] = {"repo": None}
        return None

    items = data.get("items") or []
    if not items:
        _cache[key] = {"repo": None}
        return None

    candidates = [
        RepoInfo(
            full_name=it.get("full_name", ""),
            stars=int(it.get("stargazers_count") or 0),
            url=it.get("html_url", ""),
            description=(it.get("description") or "")[:200],
            updated=it.get("updated_at", ""),
            language=it.get("language") or "",
        )
        for it in items
    ]
    official = [c for c in candidates if c.is_official]
    best = max(official or candidates, key=lambda c: c.stars)
    _cache[key] = {"repo": best}
    return best


def openalex_lookup(title: str, arxiv_id: str = "") -> dict | None:
    """取引用数与发表年份，用于"影响力"参考（不参与主排序，只展示）。"""
    key = f"oa:{arxiv_id or title[:80]}"
    if key in _cache:
        return _cache[key].get("meta")
    try:
        if arxiv_id:
            data = _get(f"{OPENALEX}?filter=doi:10.48550/arxiv.{arxiv_id}")
            results = data.get("results") or []
            if results:
                item = results[0]
                meta = {
                    "cited_by": int(item.get("cited_by_count") or 0),
                    "year": item.get("publication_year"),
                    "title": item.get("title", ""),
                }
                _cache[key] = {"meta": meta}
                return meta
        cleaned = re.sub(r"[^\w\s-]", " ", title).strip()
        data = _get(f"{OPENALEX}?search={urllib.parse.quote(cleaned)}&per-page=1")
        results = data.get("results") or []
        if not results:
            _cache[key] = {"meta": None}
            return None
        item = results[0]
        meta = {
            "cited_by": int(item.get("cited_by_count") or 0),
            "year": item.get("publication_year"),
            "title": item.get("title", ""),
        }
        _cache[key] = {"meta": meta}
        return meta
    except Exception:  # noqa: BLE001
        _cache[key] = {"meta": None}
        return None


def reproducibility(repo: RepoInfo | None) -> tuple[float, str]:
    """可复现性打分（0-1）与一句话说明。"""
    if repo is None:
        return 0.0, "未找到公开实现"
    if repo.is_official:
        return 1.0, f"官方开源实现 ★{repo.stars}"
    if repo.stars >= 100:
        return 0.85, f"社区实现 ★{repo.stars}"
    if repo.stars >= 20:
        return 0.6, f"社区实现 ★{repo.stars}"
    return 0.4, f"存在实现但关注度低 ★{repo.stars}"
