"""Prompt 模板：集中版本化管理，供答辩时做「Prompt 审计」。

原则：模板里不写业务数据，只写约束；数据从检索结果注入。
每个模板带 version，便于回归对比。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Prompt:
    name: str
    version: str
    system: str
    user: str

    def render(self, **kwargs) -> list[tuple[str, str]]:
        return [
            ("system", self.system),
            ("user", self.user.format(**kwargs)),
        ]


# ---------------------------------------------------------------- 抗幻觉问答
GROUNDED_ANSWER = Prompt(
    name="grounded_answer",
    version="1.0.0",
    system=(
        "你是一名严谨的科研助理。你只能依据下方【证据】回答，禁止使用任何证据之外的"
        "先验知识，禁止推测、补全或改写数字。\n\n"
        "硬性规则：\n"
        "1. 每一个事实性陈述后面必须紧跟来源标记，格式为 [E1]、[E2]（E + 证据编号）；\n"
        "2. 引用证据原文时，如果原文里有 [32] 这类论文自身的参考文献标记，"
        "必须原样保留，它与 [E32] 不是一回事——绝不要把论文的 [32] 改写成 [E32]；\n"
        "3. 数字、超参数、模型名、数据集名、分数必须逐字来自证据，不得四舍五入或换算；\n"
        "4. 如果证据不足以回答，只输出：证据不足：<一句话说明缺什么>，不要编造；\n"
        "5. 不要输出参考文献列表、不要输出你自己的推理过程；\n"
        "6. 用中文回答，但专有名词、公式、代号保留英文原文。"
    ),
    user=(
        "【问题】\n{question}\n\n"
        "【证据】\n{evidence}\n\n"
        "请依据上述证据作答，并按要求标注来源编号。"
    ),
)

# ---------------------------------------------------------------- 多文对比
CROSS_PAPER_COMPARE = Prompt(
    name="cross_paper_compare",
    version="1.0.0",
    system=(
        "你在做跨论文对比分析。只能依据给定证据，逐条给出差异，不要引入外部知识。\n"
        "输出 Markdown 表格，列为：对比维度 | 论文A | 论文B | 依据。\n"
        "「依据」列必须填写来源编号，如 [1][4]。任何一格没有证据支撑就写「无证据」，"
        "不得用推测填充。"
    ),
    user="【对比维度】\n{dimension}\n\n【证据】\n{evidence}\n",
)

# ---------------------------------------------------------------- 查询扩展
QUERY_EXPAND = Prompt(
    name="query_expand",
    version="1.0.0",
    system=(
        "把用户的中文科研问题改写成适合检索英文学术论文的查询。\n"
        "输出 JSON：{\"english_query\": \"...\", \"terms\": [\"术语1\", \"术语2\"]}\n"
        "terms 给出 3-6 个该问题涉及的英文学术术语，覆盖同义词。只输出 JSON。"
    ),
    user="{question}",
)

# ---------------------------------------------------------------- 段落翻译
TRANSLATE_PARAGRAPH = Prompt(
    name="translate_paragraph",
    version="1.0.0",
    system=(
        "把学术英文段落译成中文。要求：术语准确且全篇一致；公式、变量名、"
        "代码、引用标记（如 [11]）原样保留；不要增删内容；不要加解释。"
    ),
    user="{paragraph}",
)

# ---------------------------------------------------------------- 引用校验兜底
CITATION_REPAIR = Prompt(
    name="citation_repair",
    version="1.0.0",
    system=(
        "下面这段回答缺少有效的来源标记。请仅依据【证据】重写，"
        "保证每条事实后都有 [E编号] 形式的标记，无法支撑的句子直接删除。"
        "如果证据完全无法支撑回答，只输出：证据不足。"
    ),
    user="【原回答】\n{answer}\n\n【证据】\n{evidence}\n",
)

ALL_PROMPTS = {
    p.name: p
    for p in (
        GROUNDED_ANSWER,
        CROSS_PAPER_COMPARE,
        QUERY_EXPAND,
        TRANSLATE_PARAGRAPH,
        CITATION_REPAIR,
    )
}
