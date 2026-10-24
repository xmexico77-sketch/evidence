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
    version="1.1.0",
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
        "「依据」列必须填写来源编号，如 [E1][E4]。任何一格没有证据支撑就写「无证据」，"
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
        '输出 JSON：{"english_query": "...", "terms": ["术语1", "术语2"]}\n'
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

# ---------------------------------------------------------------- Idea 考古
FUTURE_JUDGE = Prompt(
    name="future_judge",
    version="1.0.0",
    system=(
        "你在判断一条「未来工作设想」是否已经被后续论文解决。\n"
        "只依据【证据】判断，不得使用外部知识。允许的结论只有三种，"
        "且必须作为回答的第一行：\n"
        "疑似已解决 —— 证据中有明确的方法或结论回应了该设想；\n"
        "部分相关证据 —— 证据与该设想相关，但没有直接解决；\n"
        "未发现解决证据 —— 证据无法支撑「已解决」的判断。\n"
        "第二行起给出理由，每个理由后标注证据编号（如 [E1]）。\n"
        "宁可判「未发现解决证据」，也不要把无关工作说成已解决。"
    ),
    user="【设想】\n{claim}\n\n【证据】\n{evidence}\n",
)

# ---------------------------------------------------------------- 领域综述
AREA_REVIEW = Prompt(
    name="area_review",
    version="1.0.0",
    system=(
        "你在为一个研究聚类撰写简短综述（200-320 字）。只能依据【文献】。\n"
        "要求：\n"
        "1. 开头一句概括该聚类共同解决什么问题；\n"
        "2. 中间按时间顺序说明方法演进（提到年份与论文名）；\n"
        "3. 结尾指出该聚类当前的局限或未解决点；\n"
        "4. 每个论断后面标注来源编号（如 [E2]）；\n"
        "5. 不要编造文献中没有的结论，不要输出参考文献列表。"
    ),
    user="【聚类主题】\n{theme}\n\n【文献】\n{evidence}\n",
)

# ---------------------------------------------------------------- 图表图注
FIGURE_CAPTION = Prompt(
    name="figure_caption",
    version="1.0.0",
    system=(
        "你在为学术论文撰写图注（Figure Caption）。要求：\n"
        "1. 第一句说明图中各变量之间的关系（不要把坐标轴名复述一遍）；\n"
        "2. 第二句提炼核心趋势或异常，必须使用给出的具体数字；\n"
        "3. 全文不超过 60 词，英文，不使用 'This figure shows' 这类空话；\n"
        "4. 只能使用给定统计量，禁止编造任何数值；\n"
        "5. 只输出图注正文，不要标题、不要编号。"
    ),
    user="图型：{kind}\n横轴：{x}\n序列：{series}\n统计量：\n{stats}\n",
)

# ---------------------------------------------------------------- 章节草稿
SECTION_DRAFT = Prompt(
    name="section_draft",
    version="1.0.0",
    system=(
        "你在为一个研究设想撰写论文的某一节草稿。只能使用【证据】中的内容。\n"
        "规则：\n"
        "1. 每个论断后用证据编号标注，格式 [C1]；不得使用不存在的编号；\n"
        "2. 不得编造文献、数据、实验设置或结论；证据没有的内容就写'（此处需作者补充）'；\n"
        "3. 学术英文，简洁，不使用营销式表达；\n"
        "4. 只输出该节正文，不要标题、不要解释。"
    ),
    user=(
        "【研究设想】{idea}\n\n【本节】{heading}——{purpose}\n\n"
        "【证据】\n{evidence}\n"
    ),
)

ALL_PROMPTS = {
    p.name: p
    for p in (
        GROUNDED_ANSWER,
        CROSS_PAPER_COMPARE,
        QUERY_EXPAND,
        TRANSLATE_PARAGRAPH,
        CITATION_REPAIR,
        FUTURE_JUDGE,
        AREA_REVIEW,
        FIGURE_CAPTION,
        SECTION_DRAFT,
    )
}
