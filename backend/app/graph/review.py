"""自动领域综述：按社区聚类组织文献，生成带引用的简短综述。

同样遵循"证据优先"原则：综述里的每个论断都要能落到具体文献块。
没有模型时退化为结构化摘要（仍带引用），有模型时走 AREA_REVIEW 提示词。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .citations import Work


@dataclass(slots=True)
class AreaReview:
    community: int
    theme: str
    members: list[str]
    year_range: str
    summary: str
    evidence: list[dict] = field(default_factory=list)
    method: str = "extractive"


def _theme_of(members: list[Work]) -> str:
    """用该聚类里基石分最高、标题最短的那篇作为主题锚点。"""
    ranked = sorted(members, key=lambda w: w.foundational, reverse=True)
    for work in ranked:
        title = work.title.strip()
        if 10 <= len(title) <= 90:
            return title
    return ranked[0].title if ranked else "未命名聚类"


def _representative_chunks(store, paper_ids: list[str], per_paper: int = 1) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for chunk in store.load_chunks():
        pid = chunk["paper_id"]
        if pid not in paper_ids or pid in seen:
            continue
        # 取该论文的第一块（通常是摘要区），信息密度最高
        out.append(chunk)
        seen.add(pid)
        if len(out) >= len(paper_ids) * per_paper:
            break
    return out


def build_area_reviews(
    works: dict[str, Work],
    store,
    llm=None,  # noqa: ANN001
    min_members: int = 3,
) -> list[AreaReview]:
    by_community: dict[int, list[Work]] = {}
    for work in works.values():
        if work.community >= 0:
            by_community.setdefault(work.community, []).append(work)

    reviews: list[AreaReview] = []
    for cid, members in sorted(by_community.items()):
        if len(members) < min_members:
            continue
        members.sort(key=lambda w: w.year)
        years = [w.year for w in members if w.year]
        year_range = f"{min(years)}–{max(years)}" if years else "年份未知"
        theme = _theme_of(members)

        paper_ids: list[str] = []
        for work in members:
            paper_ids.extend(work.members)
        chunks = _representative_chunks(store, paper_ids)

        evidence = [
            {
                "marker": f"[E{i + 1}]",
                "paper_id": c["paper_id"],
                "page": c["page_start"],
                "section": c["section_title"],
                "snippet": c["text"][:300],
            }
            for i, c in enumerate(chunks)
        ]

        if llm is not None and evidence:
            summary = _llm_summary(theme, members, evidence, llm)
            method = "llm"
        else:
            summary = _extractive_summary(theme, members, year_range)
            method = "extractive"

        reviews.append(
            AreaReview(
                community=cid,
                theme=theme,
                members=[w.title for w in members],
                year_range=year_range,
                summary=summary,
                evidence=evidence,
                method=method,
            )
        )
    return reviews


def _extractive_summary(theme: str, members: list[Work], year_range: str) -> str:
    """无模型时的结构化摘要：只说事实，不做推理。"""
    titles = "；".join(f"{w.year or '?'}《{w.title[:44]}》" for w in members)
    return (
        f"该聚类围绕「{theme[:60]}」展开，时间跨度 {year_range}，共 {len(members)} 篇。"
        f"相关文献：{titles}。"
        "（当前为结构化摘要，未启用模型生成叙述性综述。）"
    )


def _llm_summary(theme: str, members: list[Work], evidence: list[dict], llm) -> str:  # noqa: ANN001
    from ..llm.prompts import AREA_REVIEW

    ev_text = "\n".join(
        f"{e['marker']} {e['paper_id']} · p{e['page']} · §{e['section']}\n{e['snippet']}"
        for e in evidence
    )
    messages = [
        _msg(role, content)
        for role, content in AREA_REVIEW.render(theme=theme, evidence=ev_text)
    ]
    return llm.chat(messages).strip()


def _msg(role: str, content: str):  # noqa: ANN201
    from ..llm.client import Message

    return Message(role=role, content=content)
