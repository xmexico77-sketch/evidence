"""论文框架生成：从 Idea 到可核实的提纲、章节草稿与参考文献。

## 与常见"AI 写论文"工具的关键差别

参考文献只允许来自**库内已解析的真实文献**。生成后逐条核验，核验不通过的直接删除
并在 warnings 里报告——宁可少几条引用，也不出现编造的文献。

这条规则和问答链路的抗幻觉是同一个原则：任何输出都要能被外部证据支撑。
学术写作场景对"编造引用"的容忍度比编造结论更低——后者是能力问题，前者是诚信问题。

## 两种运行模式

- 有模型：按提纲逐节生成，生成后校验引用，不合格的段落降级为"要点式"
- 无模型：直接产出结构化提纲 + 证据要点（每条带原文锚点），并明确标注
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

SECTION_TEMPLATE = [
    ("Abstract", "用 150–200 词概括问题、方法、结果"),
    ("1 Introduction", "研究背景、现有方法的不足、本文动机与贡献"),
    ("2 Related Work", "按技术路线分组归纳库内相关工作，指出差异"),
    ("3 Method", "本文方法的形式化描述与关键设计"),
    ("4 Experiments", "数据集、指标、对比设置与主要结果"),
    ("5 Discussion", "局限性、失败案例分析"),
    ("6 Conclusion", "结论与未来方向"),
]

CITE_TOKEN = re.compile(r"\[(C\d{1,2})\]")


@dataclass(slots=True)
class Section:
    heading: str
    purpose: str
    draft: str = ""
    evidence: list[dict] = field(default_factory=list)
    grounded: bool = False


@dataclass(slots=True)
class Reference:
    key: str
    title: str
    paper_id: str
    year: int = 0
    arxiv_id: str = ""
    evidence_page: int = 0

    def to_line(self) -> str:
        ident = self.arxiv_id or self.paper_id
        return f"[{self.key}] {self.title}. arXiv:{ident}, {self.year or 'n.d.'}."


@dataclass(slots=True)
class Framework:
    idea: str
    title: str
    sections: list[Section]
    references: list[Reference]
    warnings: list[str] = field(default_factory=list)
    mode: str = "extractive"

    def to_dict(self) -> dict:
        return {
            "idea": self.idea,
            "title": self.title,
            "mode": self.mode,
            "sections": [
                {
                    "heading": s.heading,
                    "purpose": s.purpose,
                    "draft": s.draft,
                    "grounded": s.grounded,
                    "evidence": s.evidence,
                }
                for s in self.sections
            ],
            "references": [
                {
                    "key": r.key,
                    "title": r.title,
                    "paper_id": r.paper_id,
                    "year": r.year,
                    "arxiv_id": r.arxiv_id,
                    "evidence_page": r.evidence_page,
                    "line": r.to_line(),
                }
                for r in self.references
            ],
            "warnings": self.warnings,
        }

    def to_markdown(self) -> str:
        parts = [f"# {self.title}", ""]
        for s in self.sections:
            parts.append(f"## {s.heading}")
            parts.append(s.draft or f"（{s.purpose}）")
            parts.append("")
        parts.append("## References")
        parts.extend(r.to_line() for r in self.references)
        return "\n".join(parts)


def _norm_title(text: str) -> str:
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", text).strip()


def _guess_title(idea: str) -> str:
    """标题只做结构性改写，不编造新概念；中文设想不要套英文句式。"""
    core = idea.strip().rstrip("。.")
    if len(core) > 46:
        core = core[:46]
    if re.search(r"[\u4e00-\u9fff]", core):
        return f"{core}：研究框架"
    return f"Toward {core}"


def collect_evidence(idea: str, retriever, top_k: int = 4) -> list[dict]:  # noqa: ANN001
    hits = retriever.search(idea, top_k=top_k)
    out: list[dict] = []
    for i, h in enumerate(hits, 1):
        out.append(
            {
                "marker": f"C{i}",
                "paper_id": h["paper_id"],
                "page": h["page_start"],
                "section": h.get("section_title") or "",
                "snippet": (h["text"] or "")[:280],
                "score": h.get("score"),
            }
        )
    return out


def build_references(evidence: list[dict], papers: list[dict]) -> list[Reference]:
    """把证据涉及的论文转成可核实引用。只收库里真实存在的论文。"""
    by_id = {p["id"]: p for p in papers}
    refs: list[Reference] = []
    seen: set[str] = set()
    for ev in evidence:
        pid = ev["paper_id"]
        if pid in seen or pid not in by_id:
            continue
        seen.add(pid)
        paper = by_id[pid]
        refs.append(
            Reference(
                key=f"C{len(refs) + 1}",
                title=(paper.get("title") or pid).strip(),
                paper_id=pid,
                year=_year_of(paper.get("arxiv_id") or ""),
                arxiv_id=(paper.get("arxiv_id") or "").split("v")[0],
                evidence_page=ev["page"],
            )
        )
    return refs


def _year_of(arxiv_id: str) -> int:
    m = re.match(r"^(\d{2})(\d{2})\.", arxiv_id)
    if not m:
        return 0
    yy = int(m.group(1))
    return 2000 + yy if yy < 90 else 1900 + yy


def verify_references(refs: list[Reference], papers: list[dict]) -> tuple[list[Reference], list[str]]:
    """逐条核验：paper_id 必须存在于库中，标题非空。不合格的直接剔除。"""
    valid_ids = {p["id"] for p in papers}
    good: list[Reference] = []
    dropped: list[str] = []
    for ref in refs:
        if ref.paper_id in valid_ids and ref.title:
            good.append(ref)
        else:
            dropped.append(f"{ref.key}: {ref.title or '(空标题)'}")
    return good, dropped


def _extractive_section(section: Section, evidence: list[dict]) -> Section:
    """无模型时的草稿：只陈述证据里有什么，不做推理。"""
    if not evidence:
        section.draft = f"（本节需人工撰写：{section.purpose}）"
        section.grounded = False
        return section
    lines = [f"本节要点（依据库内文献整理，未启用模型生成）："]
    for ev in evidence[:3]:
        lines.append(
            f"- {ev['snippet'][:150]}… [{ev['marker']}]"
            f"（{ev['paper_id']} p{ev['page']}{' §' + ev['section'] if ev['section'] else ''}）"
        )
    section.draft = "\n".join(lines)
    section.evidence = evidence
    section.grounded = True
    return section


def _llm_section(section: Section, idea: str, evidence: list[dict], llm) -> Section:  # noqa: ANN001
    from ..llm.client import Message
    from ..llm.prompts import SECTION_DRAFT

    ev_text = "\n".join(
        f"[{e['marker']}] {e['paper_id']} · p{e['page']} · §{e['section']}\n{e['snippet']}"
        for e in evidence
    )
    messages = [
        Message(role=role, content=content)
        for role, content in SECTION_DRAFT.render(
            idea=idea, heading=section.heading, purpose=section.purpose, evidence=ev_text
        )
    ]
    text = llm.chat(messages).strip()
    valid_markers = {e["marker"] for e in evidence}
    used = set(CITE_TOKEN.findall(text))
    section.draft = text
    section.evidence = evidence
    # 只要引用了不存在的标记，就判定为不可信，降级为要点式
    section.grounded = bool(used) and used <= valid_markers
    if not section.grounded:
        section = _extractive_section(section, evidence)
        section.draft = "（模型草稿引用校验未通过，已降级为要点式）\n" + section.draft
    return section


def build_framework(idea: str, store, retriever, llm=None) -> Framework:  # noqa: ANN001
    idea = (idea or "").strip()
    if not idea:
        raise ValueError("idea 不能为空")

    papers = store.list_papers()
    evidence = collect_evidence(idea, retriever, top_k=5)

    refs, dropped = verify_references(build_references(evidence, papers), papers)

    sections: list[Section] = []
    for heading, purpose in SECTION_TEMPLATE:
        section = Section(heading=heading, purpose=purpose)
        # Related Work 与 Introduction 用全部证据；其余节也用同一批（库很小，够用）
        if llm is not None:
            section = _llm_section(section, idea, evidence, llm)
        else:
            section = _extractive_section(section, evidence)
        sections.append(section)

    warnings: list[str] = []
    if dropped:
        warnings.append(f"已剔除无法核实的引用 {len(dropped)} 条：" + "；".join(dropped))
    if not evidence:
        warnings.append("库中没有检索到与该 Idea 相关的内容，提纲仅有结构、无证据支撑")
    if llm is None:
        warnings.append("未配置模型：输出为结构化提纲与证据要点，未生成叙述性正文")
    ungrounded = [s.heading for s in sections if not s.grounded]
    if ungrounded:
        warnings.append("以下章节缺少可核实证据：" + "、".join(ungrounded))

    return Framework(
        idea=idea,
        title=_guess_title(idea),
        sections=sections,
        references=refs,
        warnings=warnings,
        mode="llm" if llm is not None else "extractive",
    )


def to_mermaid(framework: Framework) -> str:
    """把提纲转成 Mermaid 流程图源码（架构/行文拓扑）。"""
    lines = ["graph TD", f'  I["{framework.idea[:40]}"]']
    prev = "I"
    for i, s in enumerate(framework.sections, 1):
        node = f"S{i}"
        label = s.heading.replace('"', "'")
        lines.append(f'  {node}["{label}"]')
        lines.append(f"  {prev} --> {node}")
        prev = node
    if framework.references:
        lines.append('  R["References（库内可核实）"]')
        lines.append(f"  {prev} --> R")
    return "\n".join(lines)
