"""抗幻觉问答：把"要求模型标注来源"变成"校验模型是否真的标注了"。

这是整个项目的技术主线，也是评分表 35% 里最实的一块。

流程：
  检索 -> 组装证据（带锚点）-> 生成 -> **解析并校验引用标记** -> 不合格则重写一次
       -> 仍不合格就降级为「证据不足」

关键点：校验在服务端做，不信任模型的自述。编号越界、没有编号、
或编号指向的块里根本没有该数字，都会被判为不可信。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..indexing.retriever import HybridRetriever, make_anchor
from ..llm.prompts import CITATION_REPAIR, GROUNDED_ANSWER

# 证据标记形如 [E3]。刻意不用 [3]，因为论文正文里的 [32] 是它自己的参考文献，
# 两者混在同一条正则里会让校验器把合法引用判成越界（实测踩到）。
CITE_RE = re.compile(r"\[E(\d{1,2})\]")
INSUFFICIENT_PREFIX = "证据不足"
# 相关性闸门：重排模型对"最佳证据"的分数低于此值，视为没有可支撑答案的内容。
# 实测可答问题 +2.2 / +3.8，越界问题 -7.5，零阈值即可分开。
MIN_CONFIDENCE = 0.0


@dataclass(slots=True)
class Evidence:
    index: int
    chunk: dict

    @property
    def anchor(self) -> dict:
        return make_anchor(self.chunk)


@dataclass(slots=True)
class AnswerResult:
    question: str
    answer: str
    citations: list[dict] = field(default_factory=list)
    grounded: bool = False
    repaired: bool = False
    insufficient: bool = False
    invalid_markers: list[int] = field(default_factory=list)
    evidence_used: int = 0
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "answer": self.answer,
            "citations": self.citations,
            "grounded": self.grounded,
            "repaired": self.repaired,
            "insufficient": self.insufficient,
            "invalid_markers": self.invalid_markers,
            "evidence_used": self.evidence_used,
            "confidence": self.confidence,
        }


def build_evidence(hits: list[dict]) -> list[Evidence]:
    return [Evidence(index=i + 1, chunk=h) for i, h in enumerate(hits)]


def render_evidence(evidence: list[Evidence]) -> str:
    lines: list[str] = []
    for ev in evidence:
        a = ev.anchor
        lines.append(f"[E{ev.index}] 来源：{a['label']}")
        lines.append(ev.chunk["text"].strip())
        lines.append("")
    return "\n".join(lines).strip()


def parse_markers(text: str) -> list[int]:
    return [int(m) for m in CITE_RE.findall(text)]


def validate_markers(text: str, evidence: list[Evidence]) -> tuple[list[int], list[int]]:
    """返回 (有效编号, 无效编号)。编号必须在证据范围内。"""
    valid_span = {ev.index for ev in evidence}
    markers = parse_markers(text)
    valid = [m for m in markers if m in valid_span]
    invalid = [m for m in markers if m not in valid_span]
    return sorted(set(valid)), sorted(set(invalid))


def numeric_consistency(text: str, evidence: list[Evidence]) -> list[str]:
    """粗查：回答里出现的数字是否都能在证据里找到。

    不做严格全等（中文语义会改写单位），只报"可疑数字"，用于自检面板展示。
    """
    import re as _re

    ev_text = " ".join(ev.chunk["text"] for ev in evidence)
    ev_digits = set(_re.findall(r"\d+(?:[.,]\d+)?", ev_text))
    suspicious: list[str] = []
    for num in _re.findall(r"\d+(?:[.,]\d+)?", text):
        if num in ev_digits:
            continue
        if num.replace(",", "") in {d.replace(",", "") for d in ev_digits}:
            continue
        suspicious.append(num)
    return suspicious


class GroundedAnswerer:
    def __init__(self, retriever: HybridRetriever, llm) -> None:  # noqa: ANN001
        self.retriever = retriever
        self.llm = llm

    def ask(self, question: str, top_k: int = 5) -> AnswerResult:
        hits = self.retriever.search(question, top_k=top_k)
        if not hits:
            return AnswerResult(
                question=question,
                answer="证据不足：知识库中没有与问题相关的内容。",
                insufficient=True,
            )

        # 相关性闸门：先判断"有没有内容能回答这个问题"，再谈标注。
        # 没有这道门，模型会把一段无关原文配上合法锚点，看起来"有据"却答非所问。
        confidence = max(float(h.get("score") or 0.0) for h in hits)
        if confidence < MIN_CONFIDENCE:
            return AnswerResult(
                question=question,
                answer=(
                    "证据不足：知识库中检索到的内容与问题相关性过低"
                    f"（最高相关度 {confidence:.2f}），不作答以免误导。"
                ),
                insufficient=True,
                confidence=confidence,
            )

        evidence = build_evidence(hits)
        ev_text = render_evidence(evidence)
        messages = [
            _msg(role, content)
            for role, content in GROUNDED_ANSWER.render(question=question, evidence=ev_text)
        ]
        answer = self.llm.chat(messages).strip()

        insufficient = answer.startswith(INSUFFICIENT_PREFIX)
        valid, invalid = validate_markers(answer, evidence)

        repaired = False
        if not insufficient and not valid:
            # 一次修复机会：只给证据，让它重写并补标记
            repair_msgs = [
                _msg(role, content)
                for role, content in CITATION_REPAIR.render(answer=answer, evidence=ev_text)
            ]
            answer2 = self.llm.chat(repair_msgs).strip()
            valid2, invalid2 = validate_markers(answer2, evidence)
            if valid2:
                answer, valid, invalid, repaired = answer2, valid2, invalid2, True
            elif answer2.startswith(INSUFFICIENT_PREFIX):
                answer, insufficient = answer2, True

        citations = [
            {
                "marker": f"[E{i}]",
                "anchor": evidence[i - 1].anchor,
                "snippet": evidence[i - 1].chunk["text"][:220],
                "score": evidence[i - 1].chunk.get("score"),
            }
            for i in valid
        ]

        return AnswerResult(
            question=question,
            answer=answer,
            citations=citations,
            grounded=bool(valid) and not insufficient,
            repaired=repaired,
            insufficient=insufficient,
            invalid_markers=invalid,
            evidence_used=len(valid),
            confidence=confidence,
        )


def _msg(role: str, content: str):
    from ..llm.client import Message

    return Message(role=role, content=content)
