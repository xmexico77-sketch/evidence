"""版式泛化测试：用未参与开发的新论文检验解析鲁棒性。

为什么要做这一项：赛题明确"鼓励导入不同排版风格的论文以展现泛化性"，
而"多模态与细粒度文档解析"是 7% 的明写考察点。只在开发时那 18 篇上自证没有意义，
评审会随手丢一篇新论文进来。

判据不追求完美，追求"不崩且可诊断"：
- 每篇至少识别出 3 个标题、5 条参考文献，否则判失败
- 同时报告双栏页占比、扫描页数、引用数，异常时打印前几个标题供人工核对

用法：
  .venv\\Scripts\\python.exe scripts\\test_layouts.py            # 默认新论文集
  .venv\\Scripts\\python.exe scripts\\test_layouts.py 2103.00020 # 指定论文
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.config import PDF_DIR  # noqa: E402
from app.discovery import arxiv as A  # noqa: E402
from app.parsing import parse_pdf, summary  # noqa: E402

# 刻意选排版模板不同、且未参与开发的一组
DEFAULT_IDS = [
    "2103.00020",  # CLIP (ICML, 单栏)
    "2004.05150",  # Longformer (ACL, 双栏)
    "1506.02640",  # YOLOv1 (CVPR/IEEE, 双栏)
    "1608.06993",  # DenseNet (CVPR, 双栏)
    "2106.01345",  # Decision Transformer (NeurIPS)
]

MIN_HEADINGS = 3
MIN_REFS = 5

results: list[tuple[bool, str, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((cond, name, detail))


def layout_label(paper) -> str:  # noqa: ANN001
    """按正文特征粗判排版风格，仅用于报告，不参与断言。"""
    text = " ".join(b.text for b in paper.blocks[:80]).lower()
    if "acm reference format" in text or "ccs concepts" in text:
        return "ACM"
    if "ieee" in text and ("transactions" in text or "conference on computer vision" in text):
        return "IEEE"
    if "lncs" in text or "springer" in text:
        return "Springer/LNCS"
    two_col = sum(1 for p in paper.pages if p.columns == 2)
    ratio = two_col / max(len(paper.pages), 1)
    return f"{'双栏' if ratio > 0.3 else '单栏'}（双栏页 {two_col}/{len(paper.pages)}）"


def main() -> int:
    ids = sys.argv[1:] or DEFAULT_IDS
    print(f"测试 {len(ids)} 篇未参与开发的论文\n")
    print(f"{'arXiv':<13}{'页':>4}{'块':>6}{'标题':>6}{'文献':>6}{'引用':>6}  排版判定")
    print("-" * 78)

    for arxiv_id in ids:
        try:
            path = A.download_pdf(arxiv_id, PDF_DIR)
        except Exception as exc:  # noqa: BLE001
            check(f"{arxiv_id} 可下载", False, str(exc)[:60])
            print(f"{arxiv_id:<13}  下载失败：{str(exc)[:50]}")
            continue

        try:
            paper = parse_pdf(path)
        except Exception as exc:  # noqa: BLE001
            check(f"{arxiv_id} 可解析", False, str(exc)[:80])
            print(f"{arxiv_id:<13}  解析异常：{str(exc)[:50]}")
            continue

        st = summary(paper)
        label = layout_label(paper)
        print(
            f"{arxiv_id:<13}{st['pages']:>4}{st['blocks']:>6}{st['headings']:>6}"
            f"{st['references']:>6}{st['citations']:>6}  {label}"
        )

        check(f"{arxiv_id} 标题数 >= {MIN_HEADINGS}", st["headings"] >= MIN_HEADINGS, str(st["headings"]))
        check(f"{arxiv_id} 文献数 >= {MIN_REFS}", st["references"] >= MIN_REFS, str(st["references"]))
        check(f"{arxiv_id} 有页级锚点", st["blocks"] > 0)
        # 正文引用要能出：编号式（IEEE/CVPR）与作者-年份式（ACL/ICML）都算
        check(f"{arxiv_id} 能解析正文引用", st["citations"] > 0, str(st["citations"]))

        if st["headings"] < MIN_HEADINGS or st["references"] < MIN_REFS:
            print("    前 6 个标题：", [f"{h.number} {h.text}"[:36] for h in paper.headings[:6]])
            print("    警告：", st["warnings"][:3])

    passed = sum(1 for ok, _, _ in results if ok)
    print(f"\n{passed}/{len(results)} 项通过")
    if passed < len(results):
        print("\n有论文解析异常，需要定位：先看上面的标题树是否符合直觉，再看警告。")
        return 1
    print("全部通过：新论文的标题树与参考文献抽取均达到可用水平。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
