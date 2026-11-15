"""自检：答案是否真的被证据支撑。

为什么还需要这一层：`GroundedAnswerer` 已经在**生成时**做了三道闸
（强制标注、服务端校验编号、相关性闸门）。但那三道闸只保证"编号合法"，
不保证"编号和结论对得上"——模型完全可能拿一段讲 Adam 的原文去支撑一句
关于 BERT 的结论，编号合法、锚点可跳，读起来还很像有据。

Critic 独立于生成过程，只看两件事：

1. **编号闭合**：答案里出现的 [En] 是否都在 citations 里（不该有幽灵编号）；
2. **词面支撑**：每条引用原文与答案之间是否有实词重叠。
   没有重叠意味着"引用与结论说的不是一回事"，这是最典型的张冠李戴信号。

它刻意不做的事：不调用模型。理由有两条——自检如果也交给模型，就等于让
同一个不可靠来源给自己背书；而且它会在每次问答里多花一次 API 调用。
本实现覆盖的是可机械验证的部分，覆盖不了的部分如实标记为"未校验"。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import jieba

MARKER_RE = re.compile(r"\[E(\d{1,2})\]")
_EN = re.compile(r"[a-z][a-z0-9\-]{2,}")
MIN_OVERLAP_CHARS = 2      # 中文实词最短长度
SUPPORT_THRESHOLD = 0.5    # 至少一半引用要有词面支撑


@dataclass(slots=True)
class Critique:
    ok: bool
    issues: list[str] = field(default_factory=list)
    checks: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "issues": self.issues, "checks": self.checks}


def _tokens(text: str) -> set[str]:
    """取实词集合：英文按词、中文按 jieba 分词，去掉单字与停用字。"""
    out: set[str] = set()
    lowered = (text or "").lower()
    for w in _EN.findall(lowered):
        out.add(w)
    for span in re.findall(r"[\u4e00-\u9fff]+", text or ""):
        for t in jieba.cut(span):
            t = t.strip()
            if len(t) >= MIN_OVERLAP_CHARS:
                out.add(t)
    return out


def _marker_int(value) -> int:  # noqa: ANN001
    """把 marker 统一成整数。

    上游 build_evidence 里 marker 存的是 "[E1]" 这样的字符串，
    测试里我们更愿意直接写整数。两种都要能吃，否则自检会直接抛异常
    （第一版就是 int("[E1]") 崩了，导致 critic 事件没发出来）。
    """
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    m = re.search(r"\d+", str(value or ""))
    return int(m.group()) if m else 0


def critique(answer: str, citations: list[dict] | None, insufficient: bool = False) -> Critique:
    answer = answer or ""
    citations = citations or []
    issues: list[str] = []

    markers = [int(m) for m in MARKER_RE.findall(answer)]
    cited_markers = {_marker_int(c.get("marker")) for c in citations} - {0}

    checks: dict[str, object] = {
        "markers": len(markers),
        "citations": len(citations),
        "insufficient": insufficient,
    }

    # 拒答是合法结局：只要答案确实在说"证据不足"，就不该要求它有引用
    if insufficient:
        checks["verdict"] = "refusal"
        if markers and not cited_markers:
            issues.append("自称证据不足却仍标注了引用编号")
        return Critique(ok=not issues, issues=issues, checks=checks)

    # 1) 有结论就必须有标注
    if not markers:
        issues.append("答案没有任何 [En] 溯源标注")
    # 2) 标注必须真实存在（防幽灵编号）
    ghost = sorted(set(markers) - cited_markers)
    if ghost:
        issues.append(f"引用了不存在的证据编号：{ghost}")
    # 3) 引用原文要能支撑答案
    answer_tokens = _tokens(answer)
    supported = 0
    for c in citations:
        snippet = c.get("snippet") or ""
        if not snippet:
            continue
        if answer_tokens & _tokens(snippet):
            supported += 1
    ratio = supported / len(citations) if citations else 0.0
    checks["support_ratio"] = round(ratio, 2)
    checks["supported"] = supported
    if citations and ratio < SUPPORT_THRESHOLD:
        issues.append(
            f"引用原文与答案词面重合不足（{supported}/{len(citations)} 条有重叠），可能存在张冠李戴"
        )

    checks["verdict"] = "fail" if issues else "pass"
    return Critique(ok=not issues, issues=issues, checks=checks)
