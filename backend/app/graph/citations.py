"""引用图谱：从参考文献构建局域引文网络，并挖掘基石论文。

## 为什么基石分不直接用 PageRank

裸 PageRank 衡量的是"被多少重要文献引用"，它会把**新近热门**论文抬得很高，
但这些论文未必是"基石"。基石的定义是：**早出现，且被后续多代工作持续引用**。

所以我们用两个量相乘：

    foundational = pagerank × (0.5 + 0.5 × sustained)

其中 `sustained` = 引用它的文献里，发表时间晚于它 2 年以上的比例。
系数 0.5~1.0 是有界的：它只在同量级内调整排序，不会让 PageRank 失效，
也不会因为公式里出现一个拍脑袋的 λ 而被质疑。敏感性分析见 docs/adr/ADR-0003。
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

import networkx as nx

ARXIV_RE = re.compile(r"arXiv:\s*(\d{4}\.\d{4,5})", re.I)
YEAR_IN_ID = re.compile(r"^(\d{2})(\d{2})\.")
SUSTAINED_GAP_YEARS = 2


@dataclass(slots=True)
class Work:
    """一篇论文（合并不同版本后的逻辑作品）。"""

    key: str
    title: str
    year: int
    members: list[str] = field(default_factory=list)
    pagerank: float = 0.0
    betweenness: float = 0.0
    sustained: float = 0.0
    foundational: float = 0.0
    derivative: float = 0.0
    community: int = -1
    in_library: bool = True


def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def arxiv_base(text: str) -> str:
    m = ARXIV_RE.search(text)
    return m.group(1) if m else ""


def year_of(arxiv_id: str) -> int:
    m = YEAR_IN_ID.match(arxiv_id or "")
    if not m:
        return 0
    yy = int(m.group(1))
    return 2000 + yy if yy < 90 else 1900 + yy


def build_index(papers: list[dict]) -> tuple[dict[str, Work], dict[str, str]]:
    """建立"作品"索引：按 arXiv 基号合并版本，无 arXiv 号则按标题归一。"""
    works: dict[str, Work] = {}
    paper_to_work: dict[str, str] = {}
    for p in papers:
        pid = p["id"]
        base = (p.get("arxiv_id") or "").split("v")[0]
        title = (p.get("title") or "").strip()
        key = base or f"t:{normalize(title)[:60]}"
        if not title and not base:
            continue
        if key not in works:
            works[key] = Work(
                key=key,
                title=title or pid,
                year=year_of(base) or 0,
                members=[],
            )
        works[key].members.append(pid)
        paper_to_work[pid] = key
    return works, paper_to_work


def resolve_reference(ref_text: str, works: dict[str, Work]) -> str | None:
    """把一条参考文献文本解析为库内作品 key；解析不出返回 None。"""
    base = arxiv_base(ref_text)
    if base and base in works:
        return base

    norm_ref = normalize(ref_text)
    if not norm_ref:
        return None

    # 标题包含匹配（标题足够长才算，避免 "attention" 这类词误配）
    best: tuple[float, str] | None = None
    for key, work in works.items():
        norm_title = normalize(work.title)
        if len(norm_title) >= 25 and norm_title in norm_ref:
            score = len(norm_title) / max(len(norm_ref), 1)
            if best is None or score > best[0]:
                best = (score, key)
    if best:
        return best[1]

    # 兜底：与标题做相似度比较
    head = norm_ref[:180]
    for key, work in works.items():
        norm_title = normalize(work.title)
        if len(norm_title) < 20:
            continue
        ratio = difflib.SequenceMatcher(None, head, norm_title).ratio()
        if ratio >= 0.82 and (best is None or ratio > best[0]):
            best = (ratio, key)
    return best[1] if best else None


def build_graph(store) -> tuple[nx.DiGraph, dict[str, Work]]:  # noqa: ANN001
    papers = store.list_papers()
    works, paper_to_work = build_index(papers)
    refs = store.load_refs()

    g = nx.DiGraph()
    for key, work in works.items():
        g.add_node(key, title=work.title, year=work.year)

    matched = 0
    total_refs = 0
    for pid, items in refs.items():
        source = paper_to_work.get(pid)
        if source is None:
            continue
        for _idx, text in items:
            total_refs += 1
            target = resolve_reference(text, works)
            if target is None or target == source:
                continue
            matched += 1
            if g.has_edge(source, target):
                g[source][target]["weight"] += 1
            else:
                g.add_edge(source, target, weight=1)

    g.graph["matched_refs"] = matched
    g.graph["total_refs"] = total_refs
    return g, works


def compute_metrics(g: nx.DiGraph, works: dict[str, Work]) -> dict[str, Work]:
    if g.number_of_nodes() == 0:
        return works

    pr = nx.pagerank(g, alpha=0.85, weight="weight") if g.number_of_edges() else {}
    undirected = g.to_undirected()
    between = nx.betweenness_centrality(undirected) if undirected.number_of_edges() else {}

    for key, work in works.items():
        work.pagerank = round(pr.get(key, 0.0), 6)
        work.betweenness = round(between.get(key, 0.0), 6)

        incoming = list(g.predecessors(key)) if g.has_node(key) else []
        later = 0
        for src in incoming:
            src_year = works[src].year if src in works else 0
            if work.year and src_year and src_year - work.year >= SUSTAINED_GAP_YEARS:
                later += 1
            elif not work.year or not src_year:
                later += 1  # 年份缺失时不惩罚
        work.sustained = round(later / len(incoming), 3) if incoming else 0.0

        work.foundational = round(work.pagerank * (0.5 + 0.5 * work.sustained), 6)

        out_deg = g.out_degree(key) if g.has_node(key) else 0
        work.derivative = round((1.0 - min(work.pagerank * len(works), 1.0)) * out_deg / 10, 4)

    # 社区发现（Louvain）用无向图
    try:
        communities = nx.community.louvain_communities(undirected, seed=42)
        for cid, members in enumerate(communities):
            for key in members:
                if key in works:
                    works[key].community = cid
    except Exception:  # noqa: BLE001 - 社区发现失败不应阻断主流程
        pass
    return works


def rank_foundational(works: dict[str, Work], top: int = 5) -> list[Work]:
    """基石论文：按 foundational 排序，且必须至少被库内一篇引用。"""
    candidates = [w for w in works.values() if w.sustained > 0 or w.pagerank > 0]
    candidates.sort(key=lambda w: w.foundational, reverse=True)
    return candidates[:top]


def rank_derivative(works: dict[str, Work], top: int = 5) -> list[Work]:
    """边缘衍生：引用别人很多、但自己几乎不被引用。"""
    candidates = [w for w in works.values()]
    candidates.sort(key=lambda w: (w.pagerank == 0, w.derivative), reverse=True)
    return candidates[:top]


def to_cytoscape(works: dict[str, Work], g: nx.DiGraph) -> dict:
    """导出给前端（Cytoscape.js）的节点/边格式。"""
    max_pr = max((w.pagerank for w in works.values()), default=0.0) or 1.0
    nodes = [
        {
            "data": {
                "id": w.key,
                "label": w.title[:48] or w.key,
                "year": w.year,
                "pagerank": w.pagerank,
                "betweenness": w.betweenness,
                "sustained": w.sustained,
                "foundational": w.foundational,
                "community": w.community,
                "size": round(20 + 45 * (w.pagerank / max_pr), 1),
                "is_foundational": w.foundational >= 0.05,
            }
        }
        for w in works.values()
    ]
    edges = [
        {
            "data": {
                "id": f"{u}->{v}",
                "source": u,
                "target": v,
                "weight": d.get("weight", 1),
            }
        }
        for u, v, d in g.edges(data=True)
    ]
    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "nodes": g.number_of_nodes(),
            "edges": g.number_of_edges(),
            "matched_refs": g.graph.get("matched_refs", 0),
            "total_refs": g.graph.get("total_refs", 0),
            "density": round(nx.density(g), 4) if g.number_of_nodes() > 1 else 0.0,
        },
    }
