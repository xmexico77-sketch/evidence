"""模块六·论文框架生成验收。

重点不是"能生成文字"，而是两条底线：
1. 参考文献必须全部可在库内核实（编造的必须被剔除并报告）；
2. 模型草稿一旦引用不存在的标记，必须降级而非照发。

用法：.venv\\Scripts\\python.exe scripts\\verify_framework.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.indexing import HybridRetriever, Store  # noqa: E402
from app.llm.mock import ScriptedLLM  # noqa: E402
from app.writing.framework import (  # noqa: E402
    Reference,
    build_framework,
    to_mermaid,
    verify_references,
)

results: list[tuple[bool, str, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((cond, name, detail))


def main() -> int:
    store = Store()
    retriever = HybridRetriever(store)
    retriever.build_bm25()
    papers = store.list_papers()
    valid_ids = {p["id"] for p in papers}

    # ---- 引用核验：伪造的必须被剔除 ----
    fake = [
        Reference(key="C1", title="A Real Paper", paper_id=papers[0]["id"]),
        Reference(key="C2", title="Ghost Paper", paper_id="9999.99999"),
        Reference(key="C3", title="", paper_id=papers[0]["id"]),
    ]
    good, dropped = verify_references(fake, papers)
    check("真实引用保留", len(good) == 1 and good[0].key == "C1", str([g.key for g in good]))
    check("不存在论文被剔除", any("Ghost" in d for d in dropped), str(dropped))
    check("空标题被剔除", len(dropped) == 2, str(dropped))

    # ---- 无模型模式 ----
    fw = build_framework("用稀疏注意力降低长文本推理成本", store, retriever, llm=None)
    check("章节数 >= 6", len(fw.sections) >= 6, str(len(fw.sections)))
    check("标注为抽取式", fw.mode == "extractive", fw.mode)
    check("参考文献非空", len(fw.references) >= 1, str(len(fw.references)))
    check(
        "参考文献全部可在库内核实",
        all(r.paper_id in valid_ids for r in fw.references),
        str([r.paper_id for r in fw.references]),
    )
    check(
        "每条引用带证据页码",
        all(r.evidence_page >= 1 for r in fw.references),
        str([r.evidence_page for r in fw.references]),
    )
    check(
        "草稿含证据标记",
        any("[C" in s.draft for s in fw.sections if s.draft),
    )
    check(
        "无模型时给出说明",
        any("未配置模型" in w for w in fw.warnings),
        str(fw.warnings)[:120],
    )

    # ---- 有模型但引用造假：必须降级 ----
    bad_llm = ScriptedLLM(["我们发现该方法显著提升了性能 [C9]。"])
    fw2 = build_framework("稀疏注意力", store, retriever, llm=bad_llm)
    lowered = [s for s in fw2.sections if "降级为要点式" in s.draft]
    check("伪造引用触发降级", len(lowered) >= 1, f"{len(lowered)} 节被降级")
    check(
        "降级后不再保留伪造标记",
        all("[C9]" not in s.draft for s in fw2.sections),
    )

    # ---- 有模型且引用合法：不降级 ----
    good_llm = ScriptedLLM(["该方向已有工作给出证据 [C1]。"])
    fw3 = build_framework("稀疏注意力", store, retriever, llm=good_llm)
    check("合法引用不被降级", all("降级为要点式" not in s.draft for s in fw3.sections))
    check("合法引用模式标注为 llm", fw3.mode == "llm", fw3.mode)

    # ---- 拓扑图与导出 ----
    mermaid = to_mermaid(fw)
    check("Mermaid 含 graph TD", mermaid.startswith("graph TD"), mermaid[:30])
    check("Mermaid 含 References 节点", "References" in mermaid)
    md = fw.to_markdown()
    check("Markdown 含标题", md.startswith("# "), md[:40])
    check("Markdown 含 References 段", "## References" in md)
    check("Markdown 引用行含 arXiv", "arXiv:" in md)

    passed = sum(1 for ok, _, _ in results if ok)
    for ok, name, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))
    print(f"\n{passed}/{len(results)} 项通过 · 章节 {len(fw.sections)} · 引用 {len(fw.references)} 条")
    store.close()
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
