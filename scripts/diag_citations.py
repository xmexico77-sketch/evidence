"""诊断：为什么库内引用匹配率低。

用法：.venv\\Scripts\\python.exe scripts/diag_citations.py [paper_id]
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.graph.citations import build_index, normalize, resolve_reference  # noqa: E402
from app.indexing import Store  # noqa: E402


def main(target: str | None) -> int:
    store = Store()
    papers = store.list_papers()
    works, _ = build_index(papers)
    refs = store.load_refs()

    print(f"作品数 {len(works)}，参考文献总数 {sum(len(v) for v in refs.values())}")
    for key, work in works.items():
        print(f"  {key:<14} {work.year or '-':<6} {work.title[:56]}")

    print("\n--- 含 attention is all you need 的参考文献 ---")
    hits = 0
    for pid, items in refs.items():
        for idx, text in items:
            if "attention is all you need" in normalize(text):
                hits += 1
                if hits <= 5:
                    print(f"  [{pid}#{idx}] {text[:110]}")
    print(f"  共 {hits} 条")

    print("\n--- 各论文参考文献数 ---")
    for pid in sorted(refs):
        print(f"  {pid:<14} refs={len(refs[pid])}")

    if target:
        print(f"\n--- {target} 的前 8 条参考文献与匹配结果 ---")
        for idx, text in refs.get(target, [])[:8]:
            got = resolve_reference(text, works)
            print(f"  [{idx}] -> {got or '未匹配'} | {text[:90]}")

    store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
