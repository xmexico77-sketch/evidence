"""计划生成：把意图翻译成"要做什么"，让流程可解释也可断言。

计划是**数据**不是日志：每一步有 id、标签、说明，前端据此渲染轨迹，
测试也能断言"这个意图应该走这几步"。这样做的好处是——
评审能看清 Agent 不是黑盒，我们自己也能在改流程时发现少了一步。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .intent import Intent


@dataclass(slots=True)
class Step:
    id: str
    label: str
    detail: str = ""

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "detail": self.detail}


@dataclass(slots=True)
class Plan:
    intent: Intent
    steps: list[Step] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "intent": self.intent.value,
            "steps": [s.to_dict() for s in self.steps],
        }


# 各意图的步骤模板。id 用稳定的短名，前端与测试都按 id 匹配。
_COMMON_TAIL = [
    Step("answer", "生成带锚点的答案", "要求每个结论标注 [En]，未标注即视为不可信"),
    Step("critic", "自检证据一致性", "校验编号是否真实存在、引用原文是否支撑答案"),
]


def make_plan(intent: Intent, scoped: bool = False) -> Plan:
    if intent is Intent.PAPER_QA:
        steps = [
            Step("route", "识别意图", "已限定单篇论文，走篇内问答"),
            Step("retrieve", "篇内混合检索", "BM25 + 向量 + RRF，限定在当前论文"),
            *_COMMON_TAIL,
        ]
    elif intent is Intent.COMPARE:
        steps = [
            Step("route", "识别意图", "命中对比类问题"),
            Step("plan_compare", "确定比较对象", "需要两篇及以上论文，按篇分别取证"),
            Step("retrieve", "对照检索", "各自召回关键段落，保证两侧证据对等"),
            *_COMMON_TAIL,
        ]
    elif intent is Intent.DISCOVER:
        steps = [
            Step("route", "识别意图", "命中文献发现类问题"),
            Step("plan_discover", "确定检索偏好", "按语义相关度 + 可复现性 + 用户偏好排序"),
            Step("retrieve", "库内先行检索", "先看本地库是否已覆盖，再决定是否外检"),
            *_COMMON_TAIL,
        ]
    elif intent is Intent.REVIEW:
        steps = [
            Step("route", "识别意图", "命中综述类问题"),
            Step("plan_review", "确定时间范围", "综述需要按发表时间排序，避免把新结论当旧结论"),
            Step("retrieve", "跨篇检索", "覆盖面优先于单篇精度"),
            *_COMMON_TAIL,
        ]
    else:
        steps = [
            Step("route", "识别意图", "未限定论文，按整库问答"),
            Step("retrieve", "整库混合检索", "BM25 + 向量 + RRF 融合"),
            *_COMMON_TAIL,
        ]

    if scoped and intent is not Intent.PAPER_QA:
        # 调用方同时给了 paper_id 却又命中别的意图时，明确记录作用域被收窄
        steps.insert(1, Step("scope", "收窄检索范围", "调用方指定了论文，仅在篇内检索"))

    return Plan(intent, steps)
