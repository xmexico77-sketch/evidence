"""检查索引库状态（开发辅助）。

用法：.venv\\Scripts\\python.exe scripts/db_status.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "index" / "evidence.db"


def main() -> int:
    if not DB.exists():
        print("索引库不存在")
        return 1
    conn = sqlite3.connect(DB)
    tables = [r[0] for r in conn.execute("select name from sqlite_master where type='table'")]
    print("表：", ", ".join(tables))
    for name in ("papers", "chunks", "vectors", "refs", "blocks", "headings", "discoveries"):
        if name in tables:
            n = conn.execute(f"select count(*) from {name}").fetchone()[0]
            print(f"  {name:<12}{n}")
    if "papers" in tables:
        bad = conn.execute(
            "select id from papers where id like '%longdoc%' or id like '%udlbook%'"
        ).fetchall()
        print("库内是否混入压测文档：", [b[0] for b in bad] or "否")
        rows = conn.execute("select id, chunk_count from papers order by id").fetchall()
        print(f"文献 {len(rows)} 篇，块分布前 5：{rows[:5]}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
