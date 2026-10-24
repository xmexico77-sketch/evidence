"""开发辅助：在索引库里按关键字查块，用于验收时确认"内容在不在库里"。

用法：.venv\\Scripts\\python.exe scripts/db_grep.py "label smoothing"
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "index" / "evidence.db"


def main(needle: str, limit: int = 8) -> int:
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT id, paper_id, page_start, section_title, text FROM chunks "
        "WHERE lower(text) LIKE ? LIMIT ?",
        (f"%{needle.lower()}%", limit),
    ).fetchall()
    print(f"命中 {len(rows)} 块（模式 {needle!r}）")
    for r in rows:
        print(f"  {r[0]}  {r[1]} p{r[2]}  §{r[3]}")
        print(f"     {r[4][:160]}…")
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
