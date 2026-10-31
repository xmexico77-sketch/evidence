"""生成《作品介绍文档》：按赛题表单要求的 7 个问题组织，约 4 页。

为什么单独做：技术文档是 20 页的技术长文，结构按"概述/架构/方案/测试"展开；
而提交表单要求的是"项目详情与使用方式 / 亮点 / AI 测试落地 / 关键技术 /
图片 / 是否获奖 / 是否基于他人项目优化"这七个问题。
用一份 4 页的对照文档直接回答，评审不用在长文里找。
"""
from __future__ import annotations

import sys
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parent.parent
FIGS = ROOT / "docs" / "figures-ui"
OUT = ROOT / "docs" / "作品介绍.docx"

TEXT_W = 16.0


def set_run(run, size=10.5, bold=False, color=None, mono=False):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.name = "Consolas" if mono else "宋体"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    if color:
        run.font.color.rgb = RGBColor(*color)


def h(doc, text, level=1):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(14 if level == 1 else 8)
    p.paragraph_format.space_after = Pt(5)
    set_run(p.add_run(text), size=15 if level == 1 else 12, bold=True)
    return p


def para(doc, text, size=10.5):
    p = doc.add_paragraph()
    p.paragraph_format.first_line_indent = Cm(0.74)
    p.paragraph_format.line_spacing = 1.45
    p.paragraph_format.space_after = Pt(5)
    set_run(p.add_run(text), size=size)
    return p


def bullet(doc, text, size=10.5):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.line_spacing = 1.4
    p.paragraph_format.space_after = Pt(3)
    set_run(p.add_run(text), size=size)
    return p


def figure(doc, name: str, cap: str):
    path = FIGS / name
    if not path.exists():
        return
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(6)
    p.add_run().add_picture(str(path), width=Cm(TEXT_W))
    c = doc.add_paragraph()
    c.alignment = WD_ALIGN_PARAGRAPH.CENTER
    c.paragraph_format.space_after = Pt(8)
    set_run(c.add_run(cap), size=9, color=(0x55, 0x55, 0x55))


def build() -> Document:
    doc = Document()
    sec = doc.sections[0]
    sec.left_margin = Cm(2.6)
    sec.right_margin = Cm(2.4)
    sec.top_margin = Cm(2.2)
    sec.bottom_margin = Cm(2.0)

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run(title.add_run("证源 Evidence"), size=22, bold=True)
    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run(sub.add_run("作品介绍文档 · 第九届传智杯 AI 大模型创新应用挑战赛（省赛）"),
            size=11, color=(0x44, 0x44, 0x44))
    info = doc.add_paragraph()
    info.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run(info.add_run("B 组（本科生）｜彭嘉荣｜广州科技职业技术大学"), size=10.5)

    # ---- 1 ----
    h(doc, "一、项目详情及使用方式")
    para(doc,
         "证源 Evidence 是一个面向科研工作者的科研助手 Agent。它把「读论文」这件事拆成可核验的"
         "四步：解析、检索、回答、溯源，并保证每一个结论都能点回原文的某一页、某一段。"
         "作品覆盖六个模块：PDF 解析与语义去重、抗幻觉 RAG 与多论文对比、版式保真阅读与双语联动、"
         "arXiv 检索追踪与可复现性推荐、引用图谱与自动综述、写作辅助与数据可视化。")
    para(doc, "使用方式（三种，任选其一）：")
    bullet(doc, "在线演示：浏览器打开演示地址，用评审账号登录即可使用，无需安装。")
    bullet(doc, "本地一键：克隆仓库后运行 scripts/start.ps1，前后端同时启动（Windows / Linux 均可）。")
    bullet(doc, "容器部署：docker compose up -d，见仓库 docs/部署手册.md（含域名、HTTPS、评审账号配置）。")
    para(doc,
         "典型流程：左侧文献库选一篇论文 → 读原文并看标题树 → 就这篇提问 → "
         "点答案里的 [E1] 跳回原文那一行；或进「引用图谱」看基石论文与领域综述，"
         "进「论文发现」检索新论文并一键入库。")

    # ---- 2 ----
    h(doc, "二、项目亮点")
    bullet(doc, "段落级锚点溯源：不是给参考文献列表，而是精确到「第 7 页、第 2 段、某一行」并高亮。")
    bullet(doc, "三道抗幻觉工程约束：生成侧强制证据标记 → 服务端校验标记合法性 → 相关性闸门。"
                "答不出就明确拒答，并说明相关度，而不是编一个流畅的答案。")
    bullet(doc, "16 项可执行验收：六大模块全部有断言，一条命令跑完（约 8 分钟），评审可自行复核。")
    bullet(doc, "版式保真：降到字符坐标级重建双栏与阅读序，绕开常见库把左右两栏并进同一行的限制。")
    bullet(doc, "零特殊依赖：向量与重排全部用 ONNX（fastembed），不需要 GPU、不需要 torch、不需要外部向量库。")
    bullet(doc, "诚实的降级：未配置模型时，翻译与综述明确标注「未启用」，不伪造结果。")

    # ---- 3 ----
    h(doc, "三、AI 测试技术落地使用情况")
    para(doc,
         "作品把「评测」当成一等公民，而不是最后补几张截图。落地方式有三层：")
    bullet(doc, "断言层：16 个验收脚本覆盖解析、检索、抗幻觉、图谱、发现、可视化、写作、认证、"
                "版式泛化、长文档压测、文档一致性、依赖完整性。"
                "例如抗幻觉部分有 23 条断言：编号越界、无标记、答非所问三种情况必须判为不可信。")
    bullet(doc, "泛化层：用 5 篇开发时未见的论文（CLIP / Longformer / YOLO / DenseNet / "
                "Decision Transformer）检验解析鲁棒性；用 507 页长文档压测速度与内存"
                "（解析 187 秒、峰值内存 296MB）。")
    bullet(doc, "人工层：图表与文档排版无法用断言代替，导出后逐页目视核对——"
                "量纲混轴、表格越界这类问题都是这样发现的。")
    para(doc,
         "过程中的真实教训也写进了技术文档：验收脚本读缓存导致断言跑在旧代码上、"
         "PDF 阅读器在旧版浏览器（Edge 112）完全不可用、两个「只有接口没有界面」的半成品。"
         "这些都是先被测出来、再被修掉的。")

    # ---- 4 ----
    h(doc, "四、关键技术")
    bullet(doc, "字符级版面重建：PyMuPDF 取字符级坐标与字号，按行聚类、双栏判定、阅读序排序，"
                "再按空隙重建空格；标题树由字号、编号模式与行特征是三层判定得出。")
    bullet(doc, "混合检索：BM25（jieba 分词）与稠密向量（bge-small-en-v1.5）并列召回，"
                "RRF 融合后用多语言 CrossEncoder（bge-reranker-v2-m3-int8）重排；"
                "中文问题检索英文论文靠「术语扩展 → 原文表述」的两级召回。")
    bullet(doc, "锚点体系：段落块持久化 page + bbox，回答里的证据编号经服务端校验后映射为锚点，"
                "前端用 PDF.js 的 convertToViewportRectangle 精确高亮。")
    bullet(doc, "引用图谱度量：基石分 = PageRank × 跨代引用率（有界乘数，无自由参数），"
                "配合 Louvain 社区划分与后继工作年限做「Idea 考古」。")
    bullet(doc, "量级感知的可视化：CSV 自动选图型，检测列间量级比 ≥3 时自动分副轴，"
                "并输出图注与可复现的 matplotlib 源码。")

    # ---- 5 ----
    h(doc, "五、项目相关图片")
    para(doc, "以下截图均由脚本在真实运行的系统上抓取（无头浏览器 + DevTools 协议），非设计稿。")
    figure(doc, "01-ask.png", "图 1  限定论文提问：返回「有据」与三条锚点，各带页码与节名")
    figure(doc, "02-reader.png", "图 2  版式保真阅读：左侧原版式 PDF、中间标题树、右侧段落锚点")
    figure(doc, "03-graph.png", "图 3  引用图谱：21 节点 / 56 边 / 5 社区，金色描边为基石论文")
    figure(doc, "06-write.png", "图 4  论文框架生成：提纲与英文草稿，引用逐条核验")

    # ---- 6 ----
    h(doc, "六、是否发表过或获奖")
    para(doc,
         "本作品为本次竞赛期间独立完成的新作品，此前未以任何形式发表、未参加过其他比赛、"
         "未获得过奖项。作品使用的开源组件均为公开许可（MIT / Apache-2.0），"
         "在技术文档附录中列明。")

    # ---- 7 ----
    h(doc, "七、是否在其他项目基础上优化")
    para(doc,
         "不是。作品从零开始编写，没有任何既有项目的代码基础。"
         "所用第三方库（PyMuPDF、fastembed、NetworkX、pdfjs-dist、cytoscape 等）"
         "均为通用依赖，不包含任何针对本作品的定制代码。")
    para(doc,
         "需要说明的是，开发过程中确实借鉴了公开的研究结论（例如用跨代引用率替代"
         "经验衰减因子、用 RRF 做混合检索融合），这些属于领域通用做法，"
         "在本作品中的具体实现与参数选择为自主完成，相关取舍记录在仓库的 5 篇 ADR 中。")

    return doc


def main() -> int:
    doc = build()
    doc.save(OUT)
    print(f"已生成 {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
