"""问答 CLI：检索 -> 生成 -> 锚点校验，打印带溯源的回答。

有 DEEPSEEK_API_KEY 时用真模型；没有则用抽取式替身，
保证全链路（含 Guardrails）任何时候都能演示与回归。

用法：
  .venv\\Scripts\\python.exe scripts\\ask_cli.py "训练用了多少块 GPU？"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.indexing import HybridRetriever, Store  # noqa: E402
from app.llm import DeepSeekClient, ExtractiveLLM, has_key  # noqa: E402
from app.rag import GroundedAnswerer  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("questions", nargs="+")
    ap.add_argument("--top-k", type=int, default=5)
    args = ap.parse_args()

    store = Store()
    retriever = HybridRetriever(store)
    retriever.build_bm25()

    llm = DeepSeekClient() if has_key() else ExtractiveLLM()
    mode = "DeepSeek" if has_key() else "抽取式替身（未配置 Key）"
    print(f"模型：{mode}\n")

    answerer = GroundedAnswerer(retriever, llm)
    rc = 0
    for q in args.questions:
        res = answerer.ask(q, top_k=args.top_k)
        flag = "有据" if res.grounded else ("拒答" if res.insufficient else "未通过校验")
        print(f"Q: {q}")
        print(f"A: {res.answer}")
        print(f"   [{flag}] 引用 {res.evidence_used} 条 · 修复={res.repaired} · 无效编号={res.invalid_markers}")
        for c in res.citations:
            score = c.get("score")
            score_txt = f" score={score:+.3f}" if isinstance(score, (int, float)) else ""
            print(f"   {c['marker']} {c['anchor']['label']}{score_txt}  bbox={c['anchor']['bbox']}")
            print(f"        {c['snippet'][:100]}…")
        print()
        if not res.grounded and not res.insufficient:
            rc = 1
    store.close()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
