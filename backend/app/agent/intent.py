"""意图路由：先判断"这是哪一类问题"，再决定走哪条流程。

为什么不让所有问题走同一条路：
同一套检索流程处理"这篇论文用什么学习率"和"帮我对比这两篇的贡献"，
要么后者答成前者的样子（只回答一篇），要么前者被拖去调对比接口。
更实际的原因是：不同意图该给的**证据范围**不同——单篇问答要限定 paper_id，
否则"训练用了多少 GPU"会答成另一篇论文的数值（实测踩过）。

路由顺序（成本从低到高）：
  1. 调用方显式给了 paper_id            → 单篇问答
  2. 关键词规则（对比 / 发现 / 综述）    → 对应意图
  3. 规则判不出来且模型可用时，请模型判断 → 记录 method="llm"
  4. 仍不确定                            → 全局问答（最保守）
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Intent(str, Enum):
    PAPER_QA = "paper_qa"        # 针对某一篇论文提问
    LIBRARY_QA = "library_qa"    # 对整库提问
    COMPARE = "compare"          # 跨篇对比
    DISCOVER = "discover"        # 找新论文
    REVIEW = "review"            # 综述 / 领域脉络


COMPARE_RE = re.compile(r"对比|比较|区别|差异|异同|相比|versus|\bvs\.?\b|compare|difference", re.I)
# "最近有哪些…工作" 这类说法里既没有"论文"也没有"最新"，第一版漏掉了，
# 结果被判成整库问答。这里把"最近/近期/有哪些…(工作|方法|文献)"一并覆盖。
DISCOVER_RE = re.compile(
    r"最新|最近|近期|前沿|推荐|有什么新|新进展|新工作|"
    r"(有哪些|找一?些|帮我找|列出).{0,8}(工作|论文|文献|方法|研究)|"
    r"相关文献|recent|latest|recommend|survey of|state of the art",
    re.I,
)
REVIEW_RE = re.compile(r"综述|脉络|发展|演进|趋势|领域.{0,4}现状|总结.{0,4}方法|lineage|landscape|timeline", re.I)

# 请模型判断时只允许这几个答案，避免它自由发挥
_LLM_CHOICES = {
    "paper": Intent.PAPER_QA,
    "library": Intent.LIBRARY_QA,
    "compare": Intent.COMPARE,
    "discover": Intent.DISCOVER,
    "review": Intent.REVIEW,
}

_PROMPT = """把下面的科研问题归类，只输出一个词：
paper（针对单篇论文的细节）/ library（对整库提问）/ compare（跨篇对比）/
discover（找新论文）/ review（领域综述与脉络）。

问题：{q}
只输出那个词。"""


@dataclass(slots=True)
class IntentResult:
    intent: Intent
    method: str          # rule / llm / scope / default
    reason: str
    confidence: float    # 0–1，仅用于前端提示，不参与决策

    def to_dict(self) -> dict:
        return {
            "intent": self.intent.value,
            "method": self.method,
            "reason": self.reason,
            "confidence": round(self.confidence, 2),
        }


def route(question: str, paper_id: str | None = None, llm=None) -> IntentResult:  # noqa: ANN001
    q = (question or "").strip()

    if paper_id:
        return IntentResult(Intent.PAPER_QA, "scope", f"调用方已限定论文 {paper_id}", 1.0)

    if COMPARE_RE.search(q):
        return IntentResult(Intent.COMPARE, "rule", "命中对比类关键词", 0.85)
    if DISCOVER_RE.search(q):
        return IntentResult(Intent.DISCOVER, "rule", "命中发现类关键词", 0.8)
    if REVIEW_RE.search(q):
        return IntentResult(Intent.REVIEW, "rule", "命中综述类关键词", 0.8)

    # 规则没命中 → 兜底判断：有模型就问模型，没有就按全局问答处理
    if llm is not None:
        try:
            raw = (llm.chat([_msg("user", _PROMPT.replace("{q}", q[:400]))]) or "").strip().lower()
            word = re.sub(r"[^a-z]", "", raw.split()[0]) if raw else ""
            if word in _LLM_CHOICES:
                # 模型判成单篇但调用方没给 paper_id：无法限定范围，降级为全局
                intent = _LLM_CHOICES[word]
                if intent is Intent.PAPER_QA:
                    return IntentResult(Intent.LIBRARY_QA, "llm",
                                        "模型判为单篇但未指定论文，按整库检索", 0.6)
                return IntentResult(intent, "llm", f"模型判定为 {word}", 0.7)
        except Exception:  # noqa: BLE001 —— 路由失败不应阻塞问答
            pass

    return IntentResult(Intent.LIBRARY_QA, "default", "未命中特征，按整库问答处理", 0.5)


def _msg(role: str, content: str):  # noqa: ANN001, ANN202
    from ..llm import Message

    return Message(role, content)
