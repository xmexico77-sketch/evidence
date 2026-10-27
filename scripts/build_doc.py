"""生成技术文档 DOCX。

结构对齐赛题对技术文档的要求（项目概述/需求分析/架构/AI 方案/核心实现/
测试与部署/总结与展望），并把 ADR 里的关键决策与实测数据写进来。

用法：.venv\\Scripts\\python.exe scripts/build_doc.py
"""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "证源Evidence-技术文档.docx"

BODY_FONT = "宋体"
HEAD_FONT = "黑体"
MONO_FONT = "Consolas"


# ------------------------------------------------------------------ 基础排版
def set_run(run, *, size=10.5, bold=False, font=BODY_FONT, mono=False, color=None):
    run.font.size = Pt(size)
    run.bold = bold
    name = MONO_FONT if mono else font
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), font)
    if color:
        run.font.color.rgb = RGBColor(*color)
    return run


def para(doc, text, *, size=10.5, bold=False, align=None, space_after=6, indent=True):
    p = doc.add_paragraph()
    if indent:
        p.paragraph_format.first_line_indent = Cm(0.74)
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing = 1.35
    if align == "center":
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run(p.add_run(text), size=size, bold=bold)
    return p


def para_md(doc, text, *, size=10.5, space_after=6):
    """正文段，支持 **加粗** 内联标记（避免把星号直接印在纸上）。"""
    p = doc.add_paragraph()
    p.paragraph_format.first_line_indent = Cm(0.74)
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing = 1.35
    for i, chunk in enumerate(text.split("**")):
        if not chunk:
            continue
        set_run(p.add_run(chunk), size=size, bold=(i % 2 == 1))
    return p


def h1(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(16)
    p.paragraph_format.space_after = Pt(8)
    set_run(p.add_run(text), size=16, bold=True, font=HEAD_FONT)
    return p


def h2(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(5)
    set_run(p.add_run(text), size=12.5, bold=True, font=HEAD_FONT)
    return p


def h3(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(7)
    p.paragraph_format.space_after = Pt(4)
    set_run(p.add_run(text), size=11, bold=True, font=HEAD_FONT)
    return p


def bullet(doc, text, *, size=10.5):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.line_spacing = 1.3
    set_run(p.add_run(text), size=size)
    return p


def code(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.6)
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.line_spacing = 1.15
    set_run(p.add_run(text), size=9, mono=True, color=(0x33, 0x33, 0x33))
    return p


TEXT_WIDTH_CM = 16.0  # 21.0 - 2.6 - 2.4

UI_SHOT_DIR = ROOT / "docs" / "figures-ui"


def ui_figure(doc, filename: str, cap: str, width_cm: float = TEXT_WIDTH_CM) -> bool:
    """插入界面截图 + 图注（复用已有 figure 实现）。

    截图由 scripts/ui_shot.py 真实抓取（本机 Edge 无头模式），不是设计稿。
    文件缺失时跳过，并打印警告——文档不该因为少一张图就构建失败。
    """
    path = UI_SHOT_DIR / filename
    if not path.exists():
        print(f"  [warn] 缺少界面截图 {path}")
        return False
    figure(doc, path, width_cm, cap)
    return True


def _fixed_layout(t, total_cm: float) -> None:
    """强制固定列宽。

    坑：不能直接 append 新的 w:tblW/w:tblLayout——python-docx 已经写了一个
    w:tblW type="auto"，OOXML 里同名元素出现两次时 LibreOffice 取第一个，
    于是表格按内容自动撑开、右列被裁掉。必须原地修改已有元素。
    """
    from docx.oxml import OxmlElement

    tblPr = t._tbl.tblPr
    width = tblPr.find(qn("w:tblW"))
    if width is None:
        width = OxmlElement("w:tblW")
        tblPr.insert(0, width)
    width.set(qn("w:type"), "dxa")
    width.set(qn("w:w"), str(int(total_cm * 567)))

    layout = tblPr.find(qn("w:tblLayout"))
    if layout is None:
        layout = OxmlElement("w:tblLayout")
        tblPr.append(layout)
    layout.set(qn("w:type"), "fixed")


def table(doc, headers, rows, *, widths=None, size=9.5):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False

    # 按可用宽度等比缩放，保证任何调用都不会溢出
    if widths:
        scale = TEXT_WIDTH_CM / sum(widths)
        cols = [w * scale for w in widths]
    else:
        cols = [TEXT_WIDTH_CM / len(headers)] * len(headers)
    _fixed_layout(t, sum(cols))

    hdr = t.rows[0].cells
    for i, h in enumerate(headers):
        hdr[i].text = ""
        p = hdr[i].paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_run(p.add_run(h), size=size, bold=True, font=HEAD_FONT)
    # 跨页时重复表头
    from docx.oxml import OxmlElement

    trPr = t.rows[0]._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    trPr.append(tbl_header)

    for row in rows:
        cells = t.add_row().cells
        for i, val in enumerate(row):
            cells[i].text = ""
            p = cells[i].paragraphs[0]
            p.paragraph_format.line_spacing = 1.15
            set_run(p.add_run(str(val)), size=size)

    for i, w in enumerate(cols):
        t.columns[i].width = Cm(w)
        for row in t.rows:
            row.cells[i].width = Cm(w)

    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def caption(doc, text):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(10)
    set_run(p.add_run(text), size=9, color=(0x55, 0x55, 0x55))
    return p


def figure(doc, path: Path, width_cm: float, cap: str):
    if not path.exists():
        para(doc, f"（图缺失：{path.name}）", size=9)
        return
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(6)
    p.add_run().add_picture(str(path), width=Cm(width_cm))
    caption(doc, cap)


def page_break(doc):
    doc.add_page_break()


# ------------------------------------------------------------------ 文档
def build() -> Document:
    doc = Document()

    style = doc.styles["Normal"]
    style.font.name = BODY_FONT
    style.font.size = Pt(10.5)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), BODY_FONT)

    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.4)
    section.bottom_margin = Cm(2.2)
    section.left_margin = Cm(2.6)
    section.right_margin = Cm(2.4)

    # ---------------- 封面 ----------------
    for _ in range(4):
        doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run(p.add_run("证源 Evidence"), size=30, bold=True, font=HEAD_FONT)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run(p.add_run("带段落级锚点溯源的科研助手 Agent"), size=15, font=HEAD_FONT)

    for _ in range(2):
        doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run(p.add_run("第九届传智杯 · AI 大模型创新应用挑战赛"), size=12)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run(p.add_run("赛项：智领科研 · 意图驱动 —— 全流程科研助手构建"), size=11, color=(0x55, 0x55, 0x55))

    for _ in range(8):
        doc.add_paragraph()
    info = [
        ("文档版本", "v1.0"),
        ("参赛组别", "＿＿＿＿（研究生组 / A 组 / B 组 / C 组）"),
        ("参赛者", "＿＿＿＿"),
        ("所属院校", "＿＿＿＿"),
        ("提交日期", "2026-11-18"),
    ]
    for k, v in info:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_run(p.add_run(f"{k}：{v}"), size=11)

    page_break(doc)

    # ---------------- 摘要 ----------------
    h1(doc, "摘要")
    para(
        doc,
        "本作品面向科研工作者在文献阅读与写作中的真实痛点，构建了一个以“确定性”为核心主张的"
        "科研助手 Agent。与把大模型简单接在 PDF 上做问答的做法不同，本系统把“抗幻觉”实现为"
        "三道工程约束：生成侧强制证据标记、服务端校验标记有效性、以及相关性闸门拦截“答非所问但格式合法”"
        "的输出。系统覆盖文献解析与语义去重、抗幻觉检索问答、版式感知阅读与双语联动、"
        "自动检索追踪与推荐、引用图谱与学术综述、写作辅助与数据可视化六大模块。",
    )
    para(
        doc,
        "技术上，本文提出并实现了若干针对性设计：字符级版面重建以解决 PyMuPDF 跨栏粘行问题；"
        "混合检索加多语言交叉编码器重排以解决“中文提问检索英文论文”；时间衰减基石度量以区分"
        "“高影响”与“奠基性”；以及基于时间与语义双约束的 Idea 考古，用于识别已被后续工作解决的"
        "旧设想。所有能力均配有可执行断言脚本，系统验收不依赖人工点击。",
    )
    para(
        doc,
        "关键词：科研助手；检索增强生成；抗幻觉；版面分析；引用图谱；大语言模型",
        bold=True,
    )

    page_break(doc)

    # ---------------- 1 项目概述 ----------------
    h1(doc, "1  项目概述")

    h2(doc, "1.1  命题理解")
    para(
        doc,
        "赛题要求突破“文献管理工具”与“对话式 Chatbot”的局限，构建覆盖文献智能解析、抗幻觉问答、"
        "沉浸式对比翻译、自动检索推荐、引用图谱分析与学术写作辅助的全流程科研助手。"
        "我们认为这个命题的真正难点不在“功能多”，而在于三类矛盾：",
    )
    bullet(doc, "长文本与细粒度之间的矛盾：论文动辄数十页，但用户要的往往是某一页的一个超参数值。")
    bullet(doc, "流畅表达与学术严谨之间的矛盾：大模型擅长生成通顺句子，而学术场景要求每句话可核实。")
    bullet(doc, "通用能力与领域确定性之间的矛盾：通用模型的知识来自训练语料，而科研结论必须来自用户手上的文献。")
    para(
        doc,
        "基于此，我们没有把作品做成“功能清单的堆叠”，而是围绕一条主线展开：任何一个输出，"
        "都必须能回答“它凭什么这么说”。这条主线在系统里落成了可执行的机制，而非口号。",
    )

    h2(doc, "1.2  核心主张：确定性优于表现力")
    para(
        doc,
        "系统对“不确定”的处理是显式的：宁可回答“证据不足”，也不生成看似合理但无依据的内容。"
        "这一取舍在实现中体现为三个层次的拒绝机制（详见 4.5 节）：无锚点拒绝、锚点越界拒绝、"
        "相关度过低拒绝。我们认为，对科研工具而言，一次错误结论的代价远高于一次拒答。",
    )

    h2(doc, "1.3  交付物")
    table(
        doc,
        ["交付项", "内容", "状态"],
        [
            ["源代码", "GitHub 公开仓库，保留完整开发历史", "就绪"],
            ["技术文档", "本文档（≤30 页 PDF）", "就绪"],
            ["演示视频", "5–8 分钟，1080p，普通话讲解", "待录制"],
            ["在线演示", "可公网访问地址 + 评审专用账号", "待部署"],
            ["环境配置", ".env.example、requirements.txt、Docker、一键启动脚本", "就绪"],
        ],
        widths=[3.2, 10.5, 3.2],
    )

    # ---------------- 2 需求分析 ----------------
    h1(doc, "2  需求分析")

    h2(doc, "2.1  真实科研痛点")
    table(
        doc,
        ["痛点", "现状", "本系统的应对"],
        [
            ["信息过载", "arXiv 日均数百篇，人工筛选不可行", "自动检索追踪 + 相关性/可复现性加权推荐"],
            ["阅读效率", "跨语言、双栏、公式表格混杂", "字符级版面重建 + 双栏还原 + 双语联动"],
            ["可信度", "通用模型会编造引用与数字", "三道抗幻觉闸门 + 原文锚点回跳"],
            ["梳理成本", "手工整理领域脉络与未来方向", "引用图谱 + 基石挖掘 + Idea 考古"],
            ["产出效率", "从数据到合规图表需反复调试", "CSV 自动出学术图 + 图注 + 可复现脚本"],
        ],
        widths=[2.8, 6.2, 7.9],
    )

    h2(doc, "2.2  六大模块与实现对应")
    table(
        doc,
        ["模块", "核心要求", "本系统实现", "验收"],
        [
            ["一", "语义去重、多模态细粒度解析", "字符级重建、标题树、表格、OCR、版本合并", "verify_parse"],
            ["二", "抗幻觉 RAG、多文推理", "混合检索 + 重排 + 三道闸门", "verify_retrieval 等"],
            ["三", "版式阅读、双语联动", "PDF.js 原版式 + 锚点对齐同步滚动", "页面验证"],
            ["四", "检索追踪、智能推荐", "arXiv + GitHub + OpenAlex 加权推荐", "verify_discovery"],
            ["五", "引用图谱、综述、未来方向", "PageRank×跨代引用 + Louvain + 考古", "verify_graph 等"],
            ["六", "写作辅助、数据可视化", "学术图表 + 图注 + 脚本 + TikZ", "verify_charts"],
        ],
        widths=[1.3, 4.6, 6.4, 4.6],
        size=9,
    )

    h2(doc, "2.3  非功能需求")
    bullet(doc, "确定性：同一问题在相同库上应给出可复现的结论与锚点，不因随机性漂移。")
    bullet(doc, "可验证：所有能力提供断言脚本，评审可离线复核，不依赖演示视频。")
    bullet(doc, "可部署：单机 SQLite + 本地 ONNX 模型，无需 GPU、无需外部向量库。")
    bullet(doc, "响应性：交互查询 2 秒内返回；重计算项提供指纹缓存。")

    page_break(doc)

    # ---------------- 3 系统架构 ----------------
    h1(doc, "3  系统架构设计")

    h2(doc, "3.1  总体结构")
    code(
        doc,
        "┌──────────── Web（Next.js 15 / TypeScript）────────────┐\n"
        "│ 工作台(问答+锚点)  阅读器(PDF.js+双语)  论文发现  引用图谱  │\n"
        "└──────────────────────┬───────────────────────────────┘\n"
        "              /api 重写代理 + Cookie 会话\n"
        "┌──────────────────────┴───────────────────────────────┐\n"
        "│                 API（FastAPI）鉴权 / 线程池 / SSE       │\n"
        "├──────────────────────────────────────────────────────┤\n"
        "│ RAG：检索 → 证据组装 → 生成 → 标记校验 → 相关性闸门      │\n"
        "│ Graph：参考文献 → 实体消解 → 图 → 指标 → 基石分 → 社区   │\n"
        "│ Discovery：arXiv → GitHub/OpenAlex 补全 → 加权 → 入库   │\n"
        "├──────────────────────────────────────────────────────┤\n"
        "│ 解析：字符重建 → 标题树 → 表格/公式 → OCR → 分块 → 索引  │\n"
        "├──────────────────────────────────────────────────────┤\n"
        "│ 存储：SQLite(WAL)，论文/块/参考文献/标题树/译文/发现      │\n"
        "└──────────────────────────────────────────────────────┘",
    )
    caption(doc, "图 3-1  系统总体结构")

    h2(doc, "3.2  数据流")
    para(doc, "以“上传一篇论文”为例，系统依次执行：")
    code(
        doc,
        "sha256 查重 → 文本层检测（<100 字符/页判为扫描件）→ 字符级行重建\n"
        "→ 双栏判定与阅读序重建 → 字号聚类出标题树 → 表格/公式/参考文献抽取\n"
        "→ 语义指纹（arXiv 基号 + 标题归一 + 正文 SimHash）→ 版本冲突提示\n"
        "→ 章节感知分块 → BM25 + 稠密向量索引 → 块级 bbox 落库",
    )
    para(
        doc,
        "其中“块级 bbox 落库”是一个容易被忽略但决定成败的环节：分块时若只保存整块并集，"
        "跨页分块的 bbox 会大到整页，前端高亮将失去意义。我们为此单独持久化了 blocks 表，"
        "使引用锚点精确到一行文字。",
    )

    h2(doc, "3.3  技术选型与取舍")
    table(
        doc,
        ["层", "选型", "放弃的替代方案", "理由"],
        [
            ["前端", "Next.js 15 + TS", "Vue/Nuxt、Streamlit", "评分首选；TS 满足类型规范考察"],
            ["PDF 渲染", "PDF.js", "服务端转图片", "只有 canvas 能还原双栏并叠加 bbox 高亮"],
            ["后端", "FastAPI", "Node 全栈", "PDF/OCR/向量/图算法生态均在 Python"],
            ["解析", "PyMuPDF + RapidOCR", "MinerU、PaddleOCR", "纯 pip、无系统依赖、体积可控"],
            ["检索", "BM25 + bge-small-en + m3 重排", "仅向量检索", "术语与超参数是稀有词，稀疏通道不可替代"],
            ["向量", "fastembed（ONNX）", "sentence-transformers", "不引入 torch，省约 2.5GB 与编译风险"],
            ["图算法", "NetworkX", "自研", "成熟、结果可解释、便于评审复核"],
            ["Agent", "自研轻量 Runtime", "LangGraph、LlamaIndex", "见 3.4 节"],
            ["存储", "SQLite(WAL)", "PostgreSQL、Milvus", "单机零运维，评审一条命令即可复现"],
        ],
        widths=[1.8, 4.2, 4.2, 6.7],
        size=9,
    )

    h2(doc, "3.4  为什么不用现成 Agent 框架")
    para(
        doc,
        "这是一个有意的、且需要论证的决定。三条理由：",
    )
    bullet(
        doc,
        "可靠性。DeepSeek 的函数调用能力在官方文档中标注为 beta，参数抖动与并行调用不稳定。"
        "若把主链路交给框架，一旦模型不按 schema 输出，整条链崩溃，而框架内部的重试策略我们无法修改。",
    )
    bullet(
        doc,
        "可控性。本项目最核心的能力——锚点校验、证据不足拒答、相关性闸门——任何框架都不提供，"
        "必须自己实现。既然核心要自研，框架带来的只剩一层薄封装。",
    )
    bullet(
        doc,
        "可解释性。答辩需要讲清“Agent 如何规划、如何失败、如何降级”。自研 Runtime 的每一处"
        "状态转移都可以在代码与日志中定位，而框架的黑盒行为难以自证。",
    )
    para(
        doc,
        "因此系统采用显式状态机：意图路由 → 规划（JSON Schema 约束）→ 工具执行（并发 + 超时 + 重试）"
        "→ 证据校验 → 合成或降级。该结构在文档中同时给出与 LangGraph 的等价映射，以证明我们理解框架而非回避它。",
    )

    page_break(doc)

    # ---------------- 4 AI 技术方案 ----------------
    h1(doc, "4  AI 技术方案")

    h2(doc, "4.1  模型接入与分工")
    para(
        doc,
        "系统只依赖一个外部模型服务（DeepSeek），通过统一的 LLMProvider 抽象接入，"
        "后续可替换为其他模型而不改动业务代码。两个模型按“思考成本”分工：",
    )
    table(
        doc,
        ["用途", "模型", "理由"],
        [
            ["证据抽取、翻译、分类、字段填充", "deepseek-chat", "高频、低难度、成本敏感"],
            ["任务规划、跨文献对比、综述生成、结论判定", "deepseek-reasoner", "低频、高难度、决定输出质量"],
        ],
        widths=[7.0, 3.5, 6.4],
    )
    para(
        doc,
        "需要强调的是：没有模型时系统仍可运行。所有 LLM 调用点都提供确定性替身"
        "（抽取式问答、结构式综述、统计式图注），并在输出中显式标注“未启用模型”。"
        "这一设计既是降级策略，也保证了验收脚本可以在无网络、无密钥的环境下跑通。",
    )

    h2(doc, "4.2  解析：字符级版面重建")
    para(
        doc,
        "学术 PDF 的解析存在三个真实障碍，均通过实测发现：",
    )
    h3(doc, "（1）跨栏粘行")
    para(
        doc,
        "PyMuPDF 的 get_text(\"dict\") 会把左右两栏同一基线的文字合并进同一个 line，"
        "导致“整行横跨中缝”，任何基于行的分栏统计都会失效。我们最初的探针正是因此误判"
        "《Attention Is All You Need》v1 为双栏（实际正文为单栏，仅参考文献页为双栏）。",
    )
    h3(doc, "（2）词间空格丢失")
    para(
        doc,
        "LaTeX 生成的 PDF 常不写空格字符，而用坐标偏移表示词距，直接拼接 span 会得到"
        "“Theencoderiscomposedofastack”。系统按字符 bbox 间隙重建空格（阈值 0.18×字号）。",
    )
    h3(doc, "（3）竖排水印污染层级")
    para(
        doc,
        "arXiv 左侧的竖排编号被拆成单字行（“uJ 2”“C .s”），字号很大，会被误判为标题。"
        "系统依据 line[\"dir\"] 方向向量过滤非水平文本。",
    )
    para(
        doc,
        "解决后，系统在 v1 上得到 25 个标题、19 个章节（1/2/3/3.1/3.2/3.2.1/…/7）、"
        "41 条参考文献与 54 处正文引用，三句长正文逐字匹配通过。",
    )

    h2(doc, "4.3  检索：混合召回与重排")
    para(
        doc,
        "检索链为：BM25（jieba + 英文正则分词）与稠密向量（bge-small-en-v1.5，384 维）"
        "双路召回，RRF（k=60）融合，再由多语言交叉编码器 bge-reranker-v2-m3-int8 重排。",
    )
    para(
        doc,
        "三层缺一不可：学术文本中的术语、超参数、模型名属于稀有词，稀疏检索更准；"
        "同义改写与跨语言场景稠密检索更强；而中文提问检索英文论文时，两者都可能失手，"
        "最终由多语言交叉编码器兜底。",
    )
    table(
        doc,
        ["验证问题（中文）", "期望事实", "结果"],
        [
            ["训练用了多少块 GPU，什么型号？", "8 NVIDIA P100 GPUs", "命中，top-1"],
            ["Adam 优化器的 beta2 设成多少？", "0.98", "命中，top-3"],
            ["WMT 2014 英德任务 BLEU 是多少？", "28.4", "命中，top-3"],
            ["用了多少个注意力头？", "h = 8 parallel attention layers", "命中，top-3"],
            ["标签平滑的取值是多少？", "label smoothing of value εls = 0.1", "命中，top-1"],
            ["模型一共训练了多少 step？", "100,000", "命中，top-1"],
        ],
        widths=[7.0, 6.2, 3.7],
        size=9,
    )

    h2(doc, "4.4  查询扩展：让中文问题命中英文文献")
    para(
        doc,
        "上述 6 条查询在首轮实现中失败了 2 条（“标签平滑”“注意力头”），而用关键词检索确认内容确实在库中，"
        "说明失败发生在召回而非解析。根因是英文稠密模型对中文 query 生成的向量几乎无意义，"
        "BM25 也无法切出对应英文词，重排只能在候选集内工作，候选里没有正确块时无能为力。",
    )
    para_md(
        doc,
        "解决方案是增加一层查询扩展，把中文提问映射到英文术语空间。采用三级策略："
        "有模型时用 LLM 扩展（可处理任意领域术语），无模型时用内置术语表扩展，均缺失时原样查询。"
        "关键在于：**扩展只影响召回，最终排序仍由交叉编码器决定**，因此术语表不精确只会降低召回率，"
        "不会直接产生错误答案。改造后 6/6 命中且全部落在 top-3。",
    )

    h2(doc, "4.5  抗幻觉：三道闸门（本作品核心）")
    h3(doc, "第一道：生成侧强制标记")
    para(
        doc,
        "系统要求模型在每个事实性陈述后标注证据编号，格式为 [E1]、[E2]。"
        "刻意不使用 [1] 形式，因为论文正文自身的参考文献标记（如 [32]）会让校验器误判——"
        "这一冲突在实测中真实发生过，是改用 E 前缀的直接原因。",
    )
    h3(doc, "第二道：服务端校验")
    para(
        doc,
        "校验在服务端完成，不信任模型自述。编号越界、无编号、或指向不存在的证据，一律判为不可信。"
        "不合格时先给一次重写机会（仅提供证据，要求重写并补标记），仍不合格则降级为“证据不足”。",
    )
    h3(doc, "第三道：相关性闸门")
    para_md(
        doc,
        "这是最容易被忽略、却在实测中暴露最严重问题的一层。接口测试时提问"
        "“这篇论文的作者获得过几次图灵奖”，系统把作者列表配上完全合法的锚点返回，"
        "所有标注校验通过。这说明：**锚点只能证明文字来自原文，不能证明文字回答了问题**。",
    )
    para(doc, "系统据此引入以重排分为判据的闸门，实测区分度清晰：")
    table(
        doc,
        ["问题", "最高证据分", "系统行为"],
        [
            ["训练用了多少块 GPU", "+2.17", "作答"],
            ["标签平滑取值是多少", "+3.83", "作答"],
            ["作者获得过几次图灵奖", "−7.53", "拒答"],
        ],
        widths=[7.0, 4.0, 5.9],
    )
    para(
        doc,
        "阈值取 0 即可将可答与不可答完全分开。三道闸门共同构成了本项目对“抗幻觉”的工程化回答："
        "不是让模型更小心，而是让系统在模型出错时不输出。",
    )

    h2(doc, "4.6  图谱：基石论文度量")
    para(
        doc,
        "方案早期采用 PageRank × exp(−λΔt)，实现时发现该公式方向错误：衰减因子会奖励新论文，"
        "而“基石”的定义是早出现且被后续多代工作持续引用；同时 λ 的取值无从论证。",
    )
    para(doc, "最终采用两个有界量的乘积：")
    code(doc, "foundational = pagerank × (0.5 + 0.5 × sustained)\nsustained = 跨代引用率（引用方发表晚于该文 ≥2 年的比例）")
    para(
        doc,
        "乘数被限制在 [0.5, 1.0]，只能在同量级内调整排序，最坏情况退化为标准 PageRank；"
        "且不含自由参数，仅“2 年算一代”这一常识界定，并做了 1/2/3 年阈值敏感性分析，结论不变。"
        "在 16 篇语料上，基石榜为 Seq2Seq、Bahdanau 注意力、Transformer、Adam、BERT、LayerNorm，"
        "与领域共识一致。",
    )

    h2(doc, "4.7  Idea 考古：识别已被解决的旧设想")
    para(
        doc,
        "赛题要求“自动排除已被后续论文解决的旧 idea”。实现路径为：抽取 Future Work 陈述 →"
        "语义聚类 → 仅在晚于原论文的文献中检索 → 判断是否已被解决。",
    )
    para(
        doc,
        "第一版以重排分单一判据，37 条陈述中判出 8 条“疑似已解决”，人工抽查全部为误判。"
        "典型例：“To facilitate future work on transfer learning… we release our data set”"
        "——这根本不是研究设想，却被判为已解决。根因是重排分衡量语义相关，不衡量问题是否被解决。",
    )
    para(
        doc,
        "据此改为按能力分级：有模型时才允许下“已解决”结论；无模型时最高只到“部分相关证据”；"
        "证据分不足则为“未发现解决证据”。这一取舍的依据是错误的不对称性——"
        "把一个仍有价值的方向误判为已解决，用户会永久放弃它且无从察觉。",
    )

    h2(doc, "4.8  Prompt 工程与审计")
    para(
        doc,
        "全部提示词集中在 llm/prompts.py 中版本化管理（当前 8 个模板：证据问答、多文对比、"
        "查询扩展、段落翻译、引用修复、Idea 判定、领域综述、图注生成），每个模板带版本号。"
        "这一设计既是工程规范，也直接服务于决赛答辩要求的“Prompt 审计记录”。",
    )

    h2(doc, "4.9  性能优化策略")
    table(
        doc,
        ["问题", "现象", "措施", "效果"],
        [
            ["重排过慢", "12 候选×整块文本，单次 5.1s", "输入截断 600 字 + 多线程 + 候选池调优", "5.1s → 1.58s"],
            ["Idea 考古耗时", "37 条陈述各做一次检索", "同上 + 批量向量化", "11m43s → 85s"],
            ["综述接口", "首次 88s，评审无法等待", "按库指纹磁盘缓存", "88s → 0.03s"],
            ["长文档索引", "全书稠密索引阻塞可用性", "BM25 秒级先可用、稠密异步补齐", "冷启动可用"],
        ],
        widths=[2.8, 5.4, 5.4, 3.3],
        size=9,
    )
    para(
        doc,
        "其中“截断到 600 字”是实测下限：截断到 400 字会砍掉关键句（“8 NVIDIA P100 GPUs”"
        "恰落在 400 字之外），导致检索失败。这类阈值必须靠测试确定，不能凭直觉。",
    )

    page_break(doc)

    # ---------------- 5 核心功能实现 ----------------
    h1(doc, "5  核心功能实现")

    h2(doc, "5.1  模块一：解析与语义去重")
    bullet(doc, "字符级行重建、双栏判定、通栏分隔带、标题树（字号聚类 + 编号交叉验证）。")
    bullet(doc, "表格经 find_tables 抽取并转 Markdown；公式与引用标记保留原文。")
    bullet(doc, "扫描件按页判定后走 RapidOCR；公式区域不强识别，避免乱码污染答案。")
    bullet(doc, "语义去重：arXiv 基号 + 标题归一 + 正文 SimHash，多版本合并为同一作品节点。")

    h2(doc, "5.2  模块二：抗幻觉问答")
    bullet(doc, "章节感知分块（不跨节），保留块级 bbox 并集与块内逐段 bbox。")
    bullet(doc, "证据按 [E编号] 注入提示词，回答中的标记由服务端校验，通过后转为可点击锚点。")
    bullet(doc, "拒答输出包含原因与相关度数值，便于用户判断是“库里没有”还是“问得不对”。")

    h2(doc, "5.3  模块三：版式阅读与双语联动")
    para(
        doc,
        "前端以 PDF.js 渲染原版式，叠加 bbox 高亮层。坐标系需转换：PyMuPDF 使用左上原点、y 向下，"
        "而 PDF.js 的 convertToViewportRectangle 使用左下原点、y 向上，因此每个框需执行"
        " [x0, H−y1, x1, H−y0] 翻转，否则高亮会上下颠倒。",
    )
    para(
        doc,
        "双语联动不使用滚动比例同步（长文档必然漂移），而采用锚点对齐：PDF 侧上报（页号，页内比例），"
        "侧栏据此定位该页第 k 段；反向由顶部段落的页号与序号反算比例驱动 PDF。"
        "两方向共用一把 700ms 方向锁，避免互相驱动导致的抖动。",
    )

    h2(doc, "5.4  模块四：检索追踪与推荐")
    code(doc, "score = 0.60 × 语义相近度（与库质心） + 0.25 × 可复现性 + 0.15 × 方向偏好")
    para(
        doc,
        "相关性使用“库质心”而非单篇最相似：用户读了十余篇后，研究方向是这些文献的共同偏置。"
        "可复现性单独成项，因为无实现的新方法对科研用户价值更低，这一差异必须在排序中显式体现。"
        "点赞仅调整方向偏好而非相关性，避免推荐退化为回音室。",
    )

    h2(doc, "5.5  模块五：图谱与综述")
    bullet(doc, "参考文献实体消解（标题包含匹配 + 相似度兜底），构建有向引文网络。")
    bullet(doc, "PageRank、跨代引用率、桥接度（betweenness）、边缘衍生度四项指标。")
    bullet(doc, "Louvain 社区发现驱动自动综述；每篇综述附带证据块与页码。")
    bullet(doc, "Idea 考古输出“仍值得探索”清单，每条带原文出处与证据分。")

    h2(doc, "5.6  模块六：写作辅助与可视化")
    figure(
        doc,
        ROOT / "data" / "figures" / "training_curves-line.png",
        14.5,
        "图 5-1  系统自动生成的训练曲线图（双轴处理量纲差异）",
    )
    para(
        doc,
        "图表模块解决两个“能跑通但结果无用”的问题。其一是量纲混轴：BLEU（18–28）与损失（1.5–3.5）"
        "同轴绘制会把损失压成平线，趋势信息完全丢失，系统据量级比（≥3）自动分副轴。"
        "其二是雷达图语义：应“每行一个多边形”以对比对象，而非把各列压成一条均值线。",
    )
    para(
        doc,
        "图注只使用真实统计量（峰值位置、首末变化率），不使用“该图展示了…”式空话；"
        "同时输出可复现绘图脚本与 TikZ/pgfplots 源码。",
    )

    h2(doc, "5.7  模块六续：论文框架生成")
    para(
        doc,
        "给定一个研究设想，系统产出七节提纲（摘要、引言、相关工作、方法、实验、讨论、结论）、"
        "逐节草稿、参考文献与 Mermaid 拓扑图源码。这一模块同样贯彻“确定性优先”原则，"
        "且执行标准比问答更严：",
    )
    bullet(
        doc,
        "参考文献只能取自库内已解析文献，生成后逐条核验 paper_id 与标题；"
        "核验不通过的直接剔除，并在 warnings 中列出被剔除项。",
    )
    bullet(
        doc,
        "章节草稿若引用了不存在的证据标记（如 [C9]），整节降级为“要点式”并注明原因，"
        "而不是把带假引用的句子发出去。",
    )
    bullet(
        doc,
        "无模型时输出结构化提纲与带原文锚点的证据要点，并显式标注“未启用模型生成正文”。",
    )
    para(
        doc,
        "之所以对引用比对结论更严，是因为编造结论是能力问题、可以靠证据链纠正；"
        "编造引用是诚信问题，读者一旦发现便不再信任整个系统。",
    )

    h2(doc, "5.8  界面实录")
    para(
        doc,
        "以下截图由 scripts/ui_shot.py 在本机真实运行的系统上抓取"
        "（无头浏览器 + DevTools 协议），不是设计稿，也未做后期美化。"
        "文字与数据均为实际运行结果。",
    )

    ui_figure(
        doc,
        "01-ask.png",
        "图 5-2  工作台：限定《Attention Is All You Need》后提问，返回“有据”，"
        "三条锚点分别落在 p7 §Hardware and Schedule、p1 §Abstract、p7 §Machine Translation",
    )
    ui_figure(
        doc,
        "04-compare.png",
        "图 5-3  跨篇对比：Transformer 与 BERT 沿“自注意力与预训练目标”对齐，"
        "表格每格标注证据编号，模型对不确定之处写“未明确阐述”而不是编造承袭关系",
    )
    ui_figure(
        doc,
        "02-reader.png",
        "图 5-4  阅读器：左侧保留原版式 PDF 渲染，中间为标题树，"
        "右侧为段落级正文；三者以段落锚点双向联动（本图为 p1 状态）",
    )
    ui_figure(
        doc,
        "03-graph.png",
        "图 5-5  引用图谱：21 个节点、56 条边、5 个社区；"
        "金色描边为基石论文，节点大小按 PageRank 映射，左侧给出基石榜与边缘衍生榜",
    )
    ui_figure(
        doc,
        "05-discover.png",
        "图 5-6  论文发现：arXiv 检索结果按“60% 语义相近 + 25% 可复现性 + 15% 方向偏好”排序，"
        "支持一键入库并自动建索引",
    )
    ui_figure(
        doc,
        "06-write.png",
        "图 5-7  论文框架：7 个章节的提纲与英文草稿，每节标注“有据/待补充”，"
        "参考文献仅取自库内已解析文献并通过核验",
    )

    page_break(doc)

    # ---------------- 6 测试与部署 ----------------
    h1(doc, "6  测试与部署")

    h2(doc, "6.1  验收体系")
    para(
        doc,
        "全部能力以可执行断言呈现，一条命令输出模块级报告，不依赖人工点击与演示视频：",
    )
    code(doc, ".venv/Scripts/python.exe scripts/verify_all.py")
    table(
        doc,
        ["模块", "检查项", "结果"],
        [
            ["模块一", "解析质量（双栏/标题树/参考文献/锚点）", "通过"],
            ["模块二", "跨语言检索（中文问英文细粒度事实）", "通过"],
            ["模块二", "抗幻觉 Guardrails（编号/闸门/拒答）", "通过"],
            ["闭环", "服务层接口（健康/检索/问答/SSE/图表）", "通过"],
            ["模块五", "引用图谱（版本合并/基石榜/关键边/社区）", "通过"],
            ["模块五", "Idea 考古与自动综述（时间约束/保守判定）", "通过"],
            ["模块六", "数据可视化（选型/分轴/图注/脚本）", "通过"],
            ["模块六", "论文框架生成（引用核实/伪造剔除）", "通过"],
            ["模块四", "论文发现（去重/可复现性/反馈/BibTeX）", "通过"],
            ["交付", "认证与评审账号（登录/Cookie/Bearer/篡改）", "通过"],
            ["交付", "论文框架生成（引用核实/伪造剔除/降级）", "通过"],
        ],
        widths=[2.2, 11.0, 3.7],
    )

    h2(doc, "6.2  实测数据摘要")
    table(
        doc,
        ["指标", "数值"],
        [
            ["语料规模", "18 篇 PDF（含官方测试集 v1/v7）"],
            ["索引规模", "892 个内容块，384 维稠密向量"],
            ["解析结果（v1）", "25 标题 / 19 章节 / 41 参考文献 / 54 引用"],
            ["中文检索命中率", "6/6（全部 top-3）"],
            ["抗幻觉断言", "23/23 通过"],
            ["引用图谱", "16 节点 / 42 边 / 4 社区"],
            ["Idea 考古", "37 条陈述 / 19 类 / 6 条待探索"],
            ["交互检索耗时", "约 1.6 秒/次（含重排）"],
        ],
        widths=[6.0, 9.5],
    )

    h2(doc, "6.3  部署")
    bullet(doc, "Docker Compose：api（含健康检查）+ web（多阶段构建），模型缓存挂卷。")
    bullet(doc, "本地：scripts/start.ps1 一键启动前后端。")
    bullet(doc, "配置：.env.example 提供全部变量；密钥仅经环境变量注入，不入仓库。")
    bullet(doc, "账号：reviewer / review2026（评审）、demo / demo2026（演示），可经变量覆盖。")

    h2(doc, "6.4  已知限制（如实声明）")
    table(
        doc,
        ["限制", "影响", "说明"],
        [
            ["未配置模型时降级", "翻译/对比/综述叙述化减弱", "系统显式标注，不伪造结果"],
            ["参考文献实体消解", "个别缺号导致少边", "v1 的 37/38 号条目跨栏合并所致"],
            ["图谱为库内局域图", "规模受限于本地文献", "可接 OpenAlex 外部边扩展"],
            ["Docker 镜像未做镜像级验证", "部署存不确定性", "开发机无 Docker，依赖组合已在虚拟环境实测"],
            ["认证为演示级", "不适用于高安全场景", "密码存环境变量，无哈希/锁定/轮换"],
        ],
        widths=[4.2, 5.4, 6.3],
        size=9,
    )

    page_break(doc)

    # ---------------- 7 创新点 ----------------
    h1(doc, "7  创新点说明")

    h2(doc, "7.1  技术创新")
    table(
        doc,
        ["编号", "创新点", "与现有做法的差异"],
        [
            ["T1", "三道抗幻觉闸门", "把“抗幻觉”从提示词技巧变为服务端可验证的工程约束，其中相关性闸门解决了“格式合法但答非所问”"],
            ["T2", "字符级版面重建", "绕开 PyMuPDF 跨栏粘行这一库级限制，使双栏判定与阅读序在真实 PDF 上可用"],
            ["T3", "量级感知的分轴策略", "自动识别序列量级差异并分副轴，避免信息被压平"],
            ["T4", "时间衰减基石度量（有界乘数）", "用跨代引用率替代经验衰减因子，无自由参数、可做敏感性分析"],
            ["T5", "Idea 考古的保守判定", "按可用能力分级，无模型时不下“已解决”结论，规避最有害的误判"],
            ["T6", "锚点对齐的双语联动", "以共享段落锚点替代滚动比例映射，消除长文档双语漂移"],
        ],
        widths=[1.3, 5.2, 9.4],
        size=9,
    )

    h2(doc, "7.2  应用创新")
    table(
        doc,
        ["编号", "创新点", "用户价值"],
        [
            ["A1", "引用深链：问答卡片一键跳原文并高亮", "把“可溯源”从概念变成可操作的动作"],
            ["A2", "可复现性加权推荐", "把“有没有代码”作为显式排序因子，而非附带信息"],
            ["A3", "可复现绘图脚本随图输出", "评审/合作者可拿同一份 CSV 重画，核验成本趋近于零"],
            ["A4", "零运维单机交付", "无需 GPU、无需外部向量库，评审一条命令即可完整复现"],
        ],
        widths=[1.3, 6.4, 8.2],
        size=9,
    )

    # ---------------- 8 工程实践与教训 ----------------
    h1(doc, "8  工程实践与教训")
    para(
        doc,
        "这一节记录开发过程中真实发生过的故障与修正。之所以单独成章，是因为评审最该怀疑的"
        "不是“功能有没有做”，而是“他们知不知道自己哪里做错了”。以下每一条都配有"
        "现象、根因、修法，以及“若未发现会导致什么后果”。",
    )

    h2(doc, "8.1  三层验证体系")
    table(
        doc,
        ["层次", "手段", "能发现", "发现不了"],
        [
            ["单元断言", "verify_*.py（13 项）", "逻辑回归、边界条件、指标异常", "界面与视觉问题"],
            ["端到端冒烟", "test_web / check_deploy", "路由可达、SSR 内容、登录链路", "交互细节与排版"],
            ["人类视觉检查", "渲染图逐页核对", "排版溢出、图表可读性、信息丢失", "深层逻辑错误"],
        ],
        widths=[2.6, 5.0, 4.8, 4.6],
        size=9,
    )
    para_md(
        doc,
        "由此得出一条贯穿全项目的铁律：**验收脚本必须实时执行被测代码，不得读取缓存产物**。"
        "这条规则是用一次真实的教训换来的（见 8.2 第 1 条）。",
    )

    h2(doc, "8.2  典型故障复盘")
    table(
        doc,
        ["现象", "根因", "修法", "若未发现的后果"],
        [
            [
                "参考文献从 41 掉到 36，断言仍显示通过",
                "verify_parse 读的是 data/parsed 缓存 JSON",
                "改为实时解析 PDF",
                "解析错误长期潜伏，直到评审手上才暴露",
            ],
            [
                "三篇新论文的参考文献区整体消失",
                "碎块合并规则把“References”这种短标题并进上一段",
                "加保护名单 + 判断当前块是否标题行",
                "换一篇论文就废，且只在自己下过的语料上看不出来",
            ],
            [
                "出现 5173 字的单块",
                "flush 合并多块后没有二次切分，上限只在触发时生效",
                "上限改为硬约束，任何输出再过一遍切句",
                "向量上下文被截断，块的后半段永远检索不到",
            ],
            [
                "引用高亮框盖住整页",
                "chunk.bbox 是块内并集，跨页时等于整页",
                "新增 blocks 表持久化逐段 bbox",
                "“段落级锚点”名存实亡，退化为翻页器",
            ],
            [
                "每个页面首屏都是空白",
                "登录守卫在等待鉴权接口时返回占位文本",
                "改为后台校验、始终渲染子节点",
                "截图、首屏、SEO 全部拿到空白",
            ],
            [
                "技术文档表格右列被裁切",
                "python-docx 预置 tblW=auto，又追加了一个重复元素，渲染器取第一个",
                "原地修改已有元素并按可用宽度缩放",
                "打印稿右列缺失，评审看到的是残缺表格",
            ],
            [
                "Idea 考古判出 8 条“已解决”，人工抽查全误",
                "把重排分当作“问题是否被解决”的判据",
                "按能力分级，无模型时不下结论",
                "用户永久放弃仍有价值的方向且无从察觉",
            ],
            [
                "训练曲线里的损失被压成平线",
                "BLEU 与 loss 量级差 8 倍却共用同一坐标轴",
                "量级检测后自动分副轴",
                "图还在，但读者得不到任何趋势信息",
            ],
        ],
        widths=[4.2, 4.6, 4.2, 4.0],
        size=8.5,
    )

    h2(doc, "8.3  三条可复用的经验")
    h3(doc, "（1）错误的不对称性决定阈值该往哪边偏")
    para(
        doc,
        "抗幻觉闸门倾向于拒答、Idea 判定倾向于“未发现证据”、引用核验倾向于剔除——"
        "这三个方向看似保守，其实都基于同一个判断：把仍有价值的东西误杀，用户可以重试；"
        "把错误的东西当成正确交付，用户不会察觉。阈值必须朝“代价更大的一侧”偏。",
    )
    h3(doc, "（2）缓存是验收的头号敌人")
    para(
        doc,
        "缓存让计算变快，也让断言变假。除了脚本读缓存这一例，系统里还有两处缓存需要"
        "谨慎对待：综述结果的指纹缓存（库变了必须失效）、译文缓存（换了模型或语言需清理）。"
        "凡是缓存，都要能说清“什么条件下必然失效”。",
    )
    h3(doc, "（3）视觉正确性无法被断言替代")
    para(
        doc,
        "量纲混轴与表格溢出两个问题，所有断言都是绿的，是“把图渲染出来自己看”才发现的。"
        "因此本项目的验证流程里刻意保留了人工环节：生成图表后目视检查、导出 PDF 后逐页核对。"
        "自动化能保证“有没有”，保证不了“对不对”。",
    )

    # ---------------- 9 总结与展望 ----------------
    h1(doc, "9  总结与展望")
    para(
        doc,
        "本作品完成了一个覆盖科研全流程的助手 Agent，并在“抗幻觉”这一科研场景最关键的维度上，"
        "给出了可验证的工程答案。开发过程中的若干次自我纠错——误判单双栏、基石公式方向错误、"
        "Idea 判定过于自信、图表量纲混轴——都被记录为架构决策文档，构成作品在“学术严谨性”上的"
        "真实证据。",
    )
    para(doc, "后续可沿三个方向深化：")
    bullet(doc, "外部引文图谱：接入 OpenAlex 补全库外引用关系，把 16 篇局域图扩展为领域全景图。")
    bullet(doc, "多模态理解：引入视觉模型解析图表与公式图片，替代当前的占位策略。")
    bullet(doc, "协同与版本：支持团队共享文献库与批注，形成可积累的科研知识资产。")

    h2(doc, "附录 A  架构决策记录索引")
    table(
        doc,
        ["编号", "主题", "结论"],
        [
            ["ADR-0001", "中文查询检索英文论文", "增加查询扩展层，扩展只影响召回不影响排序"],
            ["ADR-0002", "分栏与阅读序", "字符级重建，不用 block/line 级处理"],
            ["ADR-0003", "基石论文度量", "有界乘数替代经验衰减因子，无自由参数"],
            ["ADR-0004", "Idea 考古判定", "按能力分级，无模型时不下“已解决”结论"],
        ],
        widths=[2.6, 6.2, 7.1],
        size=9,
    )

    h2(doc, "附录 B  提示词模板清单")
    table(
        doc,
        ["模板", "用途", "版本"],
        [
            ["grounded_answer", "抗幻觉证据问答", "1.1.0"],
            ["cross_paper_compare", "跨论文对比表格", "1.0.0"],
            ["query_expand", "中文查询扩展", "1.0.0"],
            ["translate_paragraph", "段落学术翻译", "1.0.0"],
            ["citation_repair", "无标记回答重写", "1.0.0"],
            ["future_judge", "Idea 是否已解决判定", "1.0.0"],
            ["area_review", "聚类综述生成", "1.0.0"],
            ["figure_caption", "学术图注生成", "1.0.0"],
        ],
        widths=[4.6, 8.0, 3.0],
        size=9,
    )

    h2(doc, "附录 C  主要接口清单")
    table(
        doc,
        ["方法", "路径", "说明"],
        [
            ["GET", "/api/health", "健康检查（公开）"],
            ["POST", "/api/login", "登录并下发会话 Cookie"],
            ["GET", "/api/papers", "文献库列表"],
            ["POST", "/api/papers", "上传 PDF 并解析入库"],
            ["POST", "/api/ask", "抗幻觉问答（含锚点，可限定单篇论文）"],
            ["POST", "/api/ask/stream", "SSE 流式问答"],
            ["POST", "/api/compare", "跨论文对比（输出带证据的表格）"],
            ["GET", "/api/papers/{id}/outline", "标题树"],
            ["GET", "/api/papers/{id}/paragraphs", "段落级正文与坐标"],
            ["POST", "/api/translate", "段落翻译（带缓存）"],
            ["POST", "/api/charts", "CSV 生成学术图表"],
            ["GET", "/api/discover", "arXiv 检索与推荐"],
            ["GET", "/api/graph", "引用图谱数据"],
            ["GET", "/api/graph/review", "自动综述与 Idea 考古"],
        ],
        widths=[2.0, 7.6, 6.4],
        size=9,
    )

    return doc


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = build()
    doc.save(OUT)
    print(f"已生成 {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
