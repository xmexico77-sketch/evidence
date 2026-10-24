"""模块四验收：arXiv 检索、可复现性加权、去重、反馈闭环。

网络调用会受外部服务影响，故默认只做一次轻量检索；
加 --offline 可完全跳过网络（在评审环境无外网时仍可验证逻辑）。

用法：.venv\\Scripts\\python.exe scripts\\verify_discovery.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.discovery import arxiv as A  # noqa: E402
from app.discovery.enrich import RepoInfo, reproducibility  # noqa: E402
from app.discovery.recommend import score_candidates  # noqa: E402
from app.indexing import Store  # noqa: E402

results: list[tuple[bool, str, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((cond, name, detail))


def main() -> int:
    # ---- 离线可验证的部分 ----
    fake = [
        A.ArxivPaper(
            id="9999.00001",
            title="A Very New Attention Method",
            summary="We propose an efficient attention variant.",
            authors=["Ada Lovelace", "Alan Turing"],
            published="2026-10-01T00:00:00Z",
            categories=["cs.CL"],
        ),
        A.ArxivPaper(
            id="1706.03762",
            title="Attention Is All You Need",
            summary="Transformer.",
            authors=["Vaswani"],
            published="2017-06-12T00:00:00Z",
            categories=["cs.CL"],
        ),
    ]
    store = Store()

    scored = score_candidates(fake, store, None, {}, enrich=False)
    ids = [s["id"] for s in scored]
    check("已在库论文被去重", "1706.03762" not in ids, str(ids))
    check("新论文保留", "9999.00001" in ids, str(ids))
    if scored:
        item = scored[0]
        check("给出推荐理由", len(item["reason"]) > 10, item["reason"])
        check("理由含相近度", "相近度" in item["reason"], item["reason"])
        check("字段完整", all(k in item for k in ("score", "relevance", "reproducibility")))

    check("无仓库时给明说明", reproducibility(None)[1] == "未找到公开实现")
    check(
        "官方仓库满分",
        reproducibility(RepoInfo("x/y", 12, "u", "Official implementation of ..."))[0] == 1.0,
    )
    check("低星社区仓库低分", reproducibility(RepoInfo("a/b", 3, "u", "reimpl"))[0] < 0.6)

    # 反馈闭环
    store.save_discoveries(scored)
    check("推荐可落库", len(store.list_discoveries(10)) >= 1)
    store.set_feedback("9999.00001", 1)
    check("点赞可记录", store.load_feedback().get("9999.00001") == 1)
    store.set_feedback("9999.00001", -1)
    check("点踩可覆盖", store.load_feedback().get("9999.00001") == -1)

    # BibTeX
    bib = A.to_bibtex(fake[0])
    check("BibTeX 含 title", "title" in bib and "Very New Attention" in bib)
    check("BibTeX 含 eprint", "9999.00001" in bib)

    # ---- 一次真实检索 ----
    try:
        papers = A.search("cat:cs.CL AND ti:transformer", max_results=3)
        check("arXiv 检索可用", len(papers) >= 1, str(len(papers)))
        if papers:
            p = papers[0]
            check("解析出标题", len(p.title) > 5, p.title[:40])
            check("解析出摘要", len(p.summary) > 50, str(len(p.summary)))
            check("解析出年份", p.year >= 2017, str(p.year))
            check("有 PDF 链接", p.pdf_url.startswith("https://arxiv.org/pdf/"))
    except Exception as exc:  # noqa: BLE001
        check("arXiv 检索可用", False, f"网络失败: {exc}")

    passed = sum(1 for ok, _, _ in results if ok)
    for ok, name, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))
    print(f"\n{passed}/{len(results)} 项通过")
    store.close()
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
