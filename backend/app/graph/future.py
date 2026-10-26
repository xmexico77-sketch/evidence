"""Idea 考古：抽取 Future Work，判断哪些设想已被后续工作解决。

这是本项目的应用创新点之一，直接对应赛题原话：
「提取多篇论文的 Future Work 部分，结合时间线与最新进展，
自动排除已被解决的旧 idea，提炼出真正具有探索价值的未来方向」。

## 为什么不能只靠大模型"读一遍说说"

大模型非常容易把"有人做过类似的事"说成"这个问题已被解决"。所以采用
**时间+语义双约束**的证据检索：

1. 只在**发表时间晚于原论文**的文献里找（时间约束，硬过滤）；
2. 用混合检索找到语义最接近的段落，取**重排分**作为相关性（语义约束）；
3. 分数不够高就返回"未发现解决证据"，而不是"未解决"——
   这两者含义完全不同，前者是证据不足，后者是结论。
4. 有 LLM 时才做判定，且要求它引用证据编号；否则只给"疑似/未发现"。

宁可漏报，不可误报：把一个仍有价值的方向判成"已解决"，是这类工具最有害的失败。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

FW_PATTERNS = [
    r"\bfuture work\b",
    r"\bin the future\b",
    r"\bfuture research\b",
    r"\bfurther (?:work|research|investigation|study)\b",
    r"\bwe leave\b.{0,60}\b(?:future|open)\b",
    r"\bremains? (?:an )?open\b",
    r"\bopen (?:problem|question|challenge)\b",
    r"\bworth (?:exploring|investigating)\b",
    r"\bcould be (?:extended|explored)\b",
]
FW_RE = re.compile("|".join(FW_PATTERNS), re.I)
# 反例：这些说法里的 "future work" 不是设想，而是数据/代码声明或客套话
FW_NEGATIVE = re.compile(
    r"facilitate future work|for future work on|to enable future work|"
    r"hope (?:that )?(?:this|our) work|we release our (?:data|code|models)",
    re.I,
)
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
MIN_LEN = 60
MAX_LEN = 420
# 判定为"疑似已解决"的重排分门槛（与相关性闸门同一量纲，实测 >1.0 才有实质相关）
RESOLVED_SCORE = 1.0
CLUSTER_COS = 0.72

STATUS_SOLVED = "疑似已解决"
STATUS_PARTIAL = "部分相关证据"
STATUS_OPEN = "未发现解决证据"
STATUS_UNKNOWN = "无法判定（无后续文献）"


@dataclass(slots=True)
class FutureItem:
    id: str
    paper_id: str
    year: int
    text: str
    page: int
    bbox: list[float]
    cluster: int = -1
    status: str = STATUS_UNKNOWN
    score: float = 0.0
    evidence: list[dict] = field(default_factory=list)


def extract_future_work(store, year_by_paper: dict[str, int]) -> list[FutureItem]:
    """在全部块里找出"未来工作"陈述，按句切分。"""
    chunks = store.load_chunks()
    items: list[FutureItem] = []
    seen: set[str] = set()
    for chunk in chunks:
        for sentence in SENT_SPLIT.split(chunk["text"]):
            s = sentence.strip()
            if not (MIN_LEN <= len(s) <= MAX_LEN):
                continue
            if not FW_RE.search(s):
                continue
            if FW_NEGATIVE.search(s):
                continue
            key = re.sub(r"\W+", "", s.lower())[:120]
            if key in seen:
                continue
            seen.add(key)
            items.append(
                FutureItem(
                    id=f"fw{len(items):04d}",
                    paper_id=chunk["paper_id"],
                    year=year_by_paper.get(chunk["paper_id"], 0),
                    text=s,
                    page=chunk["page_start"],
                    bbox=chunk["bbox"],
                )
            )
    return items


def cluster_items(items: list[FutureItem], threshold: float = CLUSTER_COS) -> int:
    """把语义相近的 Future Work 合并成一类（同一件事被多篇论文提过）。"""
    if not items:
        return 0
    from ..indexing.retriever import _dense_model

    vectors = list(_dense_model().embed([it.text for it in items], batch_size=32))
    centroids: list[list[float]] = []
    for idx, vec in enumerate(vectors):
        best_cid, best_sim = -1, -1.0
        for cid, centroid in enumerate(centroids):
            sim = _cos(vec, centroid)
            if sim > best_sim:
                best_cid, best_sim = cid, sim
        if best_sim >= threshold:
            items[idx].cluster = best_cid
        else:
            items[idx].cluster = len(centroids)
            centroids.append(list(vec))
    return len(centroids)


def _cos(a, b) -> float:  # noqa: ANN001
    import numpy as np

    va = np.asarray(a, dtype=np.float32)
    vb = np.asarray(b, dtype=np.float32)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    return float(va @ vb / denom) if denom else 0.0


# 交给模型判定的条数上限。古考是"锦上添花"的功能，不能让它把成本与耗时拖爆；
# 只判最像"已解决"的前若干条，其余保持"部分相关"，仍然不下结论。
MAX_LLM_JUDGE = 8


def assess_items(
    items: list[FutureItem],
    retriever,  # noqa: ANN001
    year_by_paper: dict[str, int],
    llm=None,  # noqa: ANN001
    top_k: int = 3,
) -> list[FutureItem]:
    """对每条 Future Work 做"是否已被后续工作解决"的证据评估。

    两趟：先算证据分并给出保守状态；再挑最像"已解决"的前 N 条交给模型判定。
    这样可以明确控制模型调用次数，而不是"有多少条调多少次"。
    """
    for item in items:
        later = {p for p, y in year_by_paper.items() if y and y > item.year}
        if not item.year or not later:
            item.status = STATUS_UNKNOWN
            continue
        hits = retriever.search(item.text, top_k=top_k, paper_filter=later)
        if not hits:
            item.status = STATUS_OPEN
            continue
        item.score = round(max(h["score"] for h in hits), 3)
        item.evidence = [
            {
                "paper_id": h["paper_id"],
                "page": h["page_start"],
                "section": h["section_title"],
                "score": h["score"],
                "snippet": h["text"][:180],
            }
            for h in hits[:2]
        ]
        # 没有模型时最高只到"部分相关"——证据分只能说明相关，不能说明已解决
        item.status = (
            STATUS_PARTIAL if item.score >= RESOLVED_SCORE else STATUS_OPEN
        )

    if llm is not None:
        candidates = sorted(
            (it for it in items if it.score >= RESOLVED_SCORE),
            key=lambda it: it.score,
            reverse=True,
        )[:MAX_LLM_JUDGE]
        for item in candidates:
            later = {p for p, y in year_by_paper.items() if y and y > item.year}
            hits = retriever.search(item.text, top_k=top_k, paper_filter=later)
            if hits:
                item.status = _judge_with_llm(item, hits, llm)

    return items


def _judge_with_llm(item: FutureItem, hits: list[dict], llm) -> str:  # noqa: ANN001
    """有模型时让模型基于证据判定；模型只能在这四种状态里选。

    单条失败不能让整批崩掉——外部模型服务会超时、会限流、会返回怪东西，
    这类考古是"锦上添花"的功能，不该拖垮主线。
    """
    from ..llm.prompts import FUTURE_JUDGE

    evidence = "\n".join(
        f"[E{i + 1}] {h['paper_id']} · p{h['page_start']} · §{h['section_title']}\n{h['text'][:600]}"
        for i, h in enumerate(hits)
    )
    messages = [
        _msg(role, content)
        for role, content in FUTURE_JUDGE.render(claim=item.text, evidence=evidence)
    ]
    try:
        raw = llm.chat(messages).strip()
    except Exception:  # noqa: BLE001
        return STATUS_PARTIAL
    head = raw.split("\n", 1)[0].strip()
    for candidate in (STATUS_SOLVED, STATUS_PARTIAL, STATUS_OPEN):
        if head.startswith(candidate):
            return candidate
    return STATUS_PARTIAL


def _msg(role: str, content: str):  # noqa: ANN201
    from ..llm.client import Message

    return Message(role=role, content=content)


def summarize_order(items: list[FutureItem], top: int = 8) -> list[FutureItem]:
    """只保留"仍值得做"的方向：优先 STATUS_OPEN，按其被提及的次数排序。"""
    counts: dict[int, int] = {}
    for it in items:
        counts[it.cluster] = counts.get(it.cluster, 0) + 1
    open_items = [it for it in items if it.status == STATUS_OPEN]
    open_items.sort(key=lambda it: (counts.get(it.cluster, 0), it.year), reverse=True)
    return open_items[:top]
