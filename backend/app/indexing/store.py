"""存储层：SQLite（WAL）存元数据与块，向量单独存 npz。

单机零运维的选择，理由见 PLAN.md：评审只需 docker compose up，
不引入 Postgres/Milvus 来增加质量风险。所有写入走单一连接 + WAL，
够单人演示规模（万级块）。
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from pathlib import Path

import numpy as np

from ..config import INDEX_DIR
from ..schema import Paper
from .chunker import Chunk

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    id           TEXT PRIMARY KEY,
    title        TEXT,
    filename     TEXT,
    sha256       TEXT,
    page_count   INTEGER,
    arxiv_id     TEXT,
    meta_json    TEXT,
    chunk_count  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS chunks (
    id           TEXT PRIMARY KEY,
    paper_id     TEXT NOT NULL,
    idx          INTEGER,
    text         TEXT NOT NULL,
    section_path TEXT,
    section_title TEXT,
    page_start   INTEGER,
    page_end     INTEGER,
    bbox         TEXT,
    block_ids    TEXT
);

CREATE INDEX IF NOT EXISTS idx_chunks_paper ON chunks(paper_id);
CREATE INDEX IF NOT EXISTS idx_chunks_sec ON chunks(section_path);

CREATE TABLE IF NOT EXISTS vectors (
    chunk_id TEXT PRIMARY KEY,
    vec      BLOB
);

CREATE TABLE IF NOT EXISTS refs (
    paper_id  TEXT NOT NULL,
    ref_index INTEGER,
    text      TEXT
);

CREATE INDEX IF NOT EXISTS idx_refs_paper ON refs(paper_id);

CREATE TABLE IF NOT EXISTS blocks (
    id         TEXT PRIMARY KEY,
    paper_id   TEXT NOT NULL,
    page       INTEGER,
    bbox       TEXT,
    order_idx  INTEGER,
    section    TEXT,
    text       TEXT
);

CREATE INDEX IF NOT EXISTS idx_blocks_paper ON blocks(paper_id);

CREATE TABLE IF NOT EXISTS headings (
    paper_id TEXT NOT NULL,
    block_id TEXT,
    text     TEXT,
    level    INTEGER,
    page     INTEGER,
    bbox     TEXT,
    number   TEXT,
    path     TEXT
);

CREATE INDEX IF NOT EXISTS idx_headings_paper ON headings(paper_id);

CREATE TABLE IF NOT EXISTS translations (
    paper_id TEXT NOT NULL,
    block_id TEXT NOT NULL,
    lang     TEXT NOT NULL,
    text     TEXT,
    PRIMARY KEY (paper_id, block_id, lang)
);

CREATE TABLE IF NOT EXISTS discoveries (
    id              TEXT PRIMARY KEY,
    title           TEXT,
    summary         TEXT,
    authors         TEXT,
    published       TEXT,
    categories      TEXT,
    relevance       REAL,
    reproducibility REAL,
    score           REAL,
    reason          TEXT,
    repo            TEXT,
    repo_stars      INTEGER,
    cited_by        INTEGER,
    fetched_at      TEXT
);

CREATE TABLE IF NOT EXISTS feedback (
    discovery_id TEXT PRIMARY KEY,
    verdict      INTEGER,
    at           TEXT
);
"""


class Store:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else INDEX_DIR / "evidence.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # FastAPI 的 run_in_threadpool 会让同一连接跨线程使用，
        # 因此放开线程检查，并用一把写锁串行化写入（WAL 下读不阻塞）。
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self._lock = threading.Lock()
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ---------- 写入 ----------
    def upsert_paper(self, paper: Paper, chunks: list[Chunk]) -> None:
        with self._lock:
            self._upsert_paper_locked(paper, chunks)

    def _upsert_paper_locked(self, paper: Paper, chunks: list[Chunk]) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO papers "
            "(id,title,filename,sha256,page_count,arxiv_id,meta_json,chunk_count) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                paper.id,
                paper.title,
                paper.filename,
                paper.sha256,
                paper.page_count,
                paper.arxiv_id,
                json.dumps(
                    {
                        "authors": paper.authors,
                        "abstract": paper.abstract,
                        "doi": paper.doi,
                        "warnings": paper.warnings,
                        "tables": len(paper.tables),
                        "references": len(paper.references),
                    },
                    ensure_ascii=False,
                ),
                len(chunks),
            ),
        )
        cur.execute("DELETE FROM chunks WHERE paper_id=?", (paper.id,))
        cur.execute("DELETE FROM vectors WHERE chunk_id LIKE ?", (f"{paper.id}#%",))
        cur.execute("DELETE FROM refs WHERE paper_id=?", (paper.id,))
        cur.executemany(
            "INSERT INTO chunks (id,paper_id,idx,text,section_path,section_title,"
            "page_start,page_end,bbox,block_ids) VALUES (?,?,?,?,?,?,?,?,?,?)",
            [c.to_row() for c in chunks],
        )
        cur.executemany(
            "INSERT INTO refs (paper_id,ref_index,text) VALUES (?,?,?)",
            [(paper.id, r.index, r.text) for r in paper.references],
        )
        cur.execute("DELETE FROM blocks WHERE paper_id=?", (paper.id,))
        cur.executemany(
            "INSERT INTO blocks (id,paper_id,page,bbox,order_idx,section,text) "
            "VALUES (?,?,?,?,?,?,?)",
            [
                (
                    b.id,
                    paper.id,
                    b.page,
                    ",".join(f"{v:.2f}" for v in b.bbox.to_list()),
                    b.order,
                    b.section_path,
                    b.text,
                )
                for b in paper.blocks
            ],
        )
        cur.execute("DELETE FROM headings WHERE paper_id=?", (paper.id,))
        cur.executemany(
            "INSERT INTO headings (paper_id,block_id,text,level,page,bbox,number,path) "
            "VALUES (?,?,?,?,?,?,?,?)",
            [
                (
                    paper.id,
                    h.block_id,
                    h.text,
                    h.level,
                    h.page,
                    ",".join(f"{v:.2f}" for v in h.bbox.to_list()),
                    h.number,
                    h.path,
                )
                for h in paper.headings
            ],
        )
        self.conn.commit()

    def save_vectors(self, chunk_ids: list[str], matrix: np.ndarray) -> None:
        with self._lock:
            self.conn.executemany(
                "INSERT OR REPLACE INTO vectors (chunk_id, vec) VALUES (?,?)",
                [
                    (cid, matrix[i].astype(np.float32).tobytes())
                    for i, cid in enumerate(chunk_ids)
                ],
            )
            self.conn.commit()

    def delete_paper(self, paper_id: str) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM chunks WHERE paper_id=?", (paper_id,))
            self.conn.execute("DELETE FROM vectors WHERE chunk_id LIKE ?", (f"{paper_id}#%",))
            self.conn.execute("DELETE FROM papers WHERE id=?", (paper_id,))
            self.conn.commit()

    # ---------- 读取 ----------
    def list_papers(self) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT id,title,filename,page_count,arxiv_id,chunk_count FROM papers ORDER BY id"
            ).fetchall()
        return [
            {
                "id": r[0],
                "title": r[1],
                "filename": r[2],
                "pages": r[3],
                "arxiv_id": r[4],
                "chunks": r[5],
            }
            for r in rows
        ]

    def load_chunks(self) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT id,paper_id,idx,text,section_path,section_title,page_start,page_end,bbox "
                "FROM chunks ORDER BY paper_id, idx"
            ).fetchall()
        out = []
        for r in rows:
            out.append(
                {
                    "id": r[0],
                    "paper_id": r[1],
                    "index": r[2],
                    "text": r[3],
                    "section_path": r[4],
                    "section_title": r[5],
                    "page_start": r[6],
                    "page_end": r[7],
                    "bbox": [float(x) for x in (r[8] or "").split(",") if x],
                }
            )
        return out

    def load_paragraphs(self, paper_id: str) -> list[dict]:
        """段落级正文 + 坐标。双语侧栏与联动滚动都靠它。

        开头要做一次裁剪：论文首页的标题、作者列表、单位、邮箱、脚注
        都会被切成独立小块，直接铺进右侧栏会出现"Attention Is All You
        Need / Ashish Vaswani*"刷屏——实测首屏 12 行里 9 行是作者信息，
        正文反而被挤到下面。这里从摘要（或第一个编号章节）开始截取。
        """
        with self._lock:
            rows = self.conn.execute(
                "SELECT id,page,bbox,section,text,order_idx FROM blocks "
                "WHERE paper_id=? ORDER BY order_idx",
                (paper_id,),
            ).fetchall()
            headings = self.conn.execute(
                "SELECT text FROM headings WHERE paper_id=? ORDER BY page",
                (paper_id,),
            ).fetchall()
        items = [
            {
                "id": r[0],
                "page": r[1],
                "bbox": [float(x) for x in (r[2] or "").split(",") if x],
                "section": r[3],
                "text": r[4] or "",
                "order": r[5],
            }
            for r in rows
            if (r[4] or "").strip()
        ]
        return _trim_front_matter(items, [h[0] or "" for h in headings])

    def load_translations(self, paper_id: str, lang: str) -> dict[str, str]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT block_id, text FROM translations WHERE paper_id=? AND lang=?",
                (paper_id, lang),
            ).fetchall()
        return {r[0]: r[1] for r in rows}

    def save_translations(
        self, paper_id: str, lang: str, mapping: dict[str, str]
    ) -> None:
        if not mapping:
            return
        with self._lock:
            self.conn.executemany(
                "INSERT OR REPLACE INTO translations (paper_id,block_id,lang,text) "
                "VALUES (?,?,?,?)",
                [(paper_id, bid, lang, txt) for bid, txt in mapping.items()],
            )
            self.conn.commit()

    def save_discoveries(self, items: list[dict]) -> None:
        if not items:
            return
        with self._lock:
            self.conn.executemany(
                "INSERT OR REPLACE INTO discoveries "
                "(id,title,summary,authors,published,categories,relevance,reproducibility,"
                "score,reason,repo,repo_stars,cited_by,fetched_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        d["id"],
                        d["title"],
                        d.get("summary", ""),
                        d.get("authors", ""),
                        d.get("published", ""),
                        d.get("categories", ""),
                        d.get("relevance", 0.0),
                        d.get("reproducibility", 0.0),
                        d.get("score", 0.0),
                        d.get("reason", ""),
                        d.get("repo", ""),
                        d.get("repo_stars", 0),
                        d.get("cited_by", 0),
                        d.get("fetched_at", ""),
                    )
                    for d in items
                ],
            )
            self.conn.commit()

    def list_discoveries(self, limit: int = 30) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT id,title,summary,authors,published,categories,relevance,"
                "reproducibility,score,reason,repo,repo_stars,cited_by,fetched_at "
                "FROM discoveries ORDER BY score DESC, fetched_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        keys = [
            "id",
            "title",
            "summary",
            "authors",
            "published",
            "categories",
            "relevance",
            "reproducibility",
            "score",
            "reason",
            "repo",
            "repo_stars",
            "cited_by",
            "fetched_at",
        ]
        return [dict(zip(keys, r, strict=False)) for r in rows]

    def set_feedback(self, discovery_id: str, verdict: int) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO feedback (discovery_id, verdict, at) VALUES (?,?,?)",
                (discovery_id, verdict, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
            )
            self.conn.commit()

    def load_feedback(self) -> dict[str, int]:
        with self._lock:
            rows = self.conn.execute("SELECT discovery_id, verdict FROM feedback").fetchall()
        return {r[0]: int(r[1]) for r in rows}

    def get_paper(self, paper_id: str) -> dict | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT id,title,filename,page_count,arxiv_id,sha256 FROM papers WHERE id=?",
                (paper_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "title": row[1],
            "filename": row[2],
            "pages": row[3],
            "arxiv_id": row[4],
            "sha256": row[5],
        }

    def load_outline(self, paper_id: str) -> list[dict]:
        """标题树：阅读器左侧导航用。"""
        with self._lock:
            rows = self.conn.execute(
                "SELECT text,level,page,bbox,number,path,block_id FROM headings "
                "WHERE paper_id=? ORDER BY block_id",
                (paper_id,),
            ).fetchall()
        return [
            {
                "text": r[0],
                "level": r[1],
                "page": r[2],
                "bbox": [float(x) for x in (r[3] or "").split(",") if x],
                "number": r[4],
                "path": r[5],
                "block_id": r[6],
            }
            for r in rows
        ]

    def load_references(self, paper_id: str) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT ref_index,text FROM refs WHERE paper_id=? ORDER BY ref_index",
                (paper_id,),
            ).fetchall()
        return [{"index": r[0], "text": r[1]} for r in rows]

    def load_pages_blocks(self, paper_id: str) -> dict[int, list[dict]]:
        """按页分组的文本块，阅读器用来做"原文定位"与段落点击。"""
        with self._lock:
            rows = self.conn.execute(
                "SELECT id,page,bbox,section FROM blocks WHERE paper_id=? ORDER BY order_idx",
                (paper_id,),
            ).fetchall()
        out: dict[int, list[dict]] = {}
        for bid, page, bbox, section in rows:
            out.setdefault(page, []).append(
                {
                    "id": bid,
                    "bbox": [float(x) for x in (bbox or "").split(",") if x],
                    "section": section,
                }
            )
        return out

    def load_refs(self) -> dict[str, list[tuple[int, str]]]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT paper_id, ref_index, text FROM refs ORDER BY paper_id, ref_index"
            ).fetchall()
        out: dict[str, list[tuple[int, str]]] = {}
        for paper_id, idx, text in rows:
            out.setdefault(paper_id, []).append((idx, text))
        return out

    def boxes_for_chunks(self, chunk_ids: list[str]) -> dict[str, list[dict]]:
        """返回每个块内**逐段 bbox**。

        chunk.bbox 是整块并集，跨页时会大到整页（实测出现过 72→722），
        前端拿去做高亮毫无意义。真正能用于高亮的是块内每一段的 bbox。
        """
        if not chunk_ids:
            return {}
        marks = ",".join("?" * len(chunk_ids))
        with self._lock:
            rows = self.conn.execute(
                f"SELECT id, block_ids FROM chunks WHERE id IN ({marks})", chunk_ids
            ).fetchall()
            wanted: dict[str, list[str]] = {}
            all_ids: list[str] = []
            for cid, block_ids in rows:
                ids = [b for b in (block_ids or "").split("|") if b]
                wanted[cid] = ids
                all_ids.extend(ids)
            if not all_ids:
                return {}
            marks2 = ",".join("?" * len(all_ids))
            brows = self.conn.execute(
                f"SELECT id, page, bbox FROM blocks WHERE id IN ({marks2})", all_ids
            ).fetchall()
        box_by_block = {
            bid: {
                "page": page,
                "bbox": [float(x) for x in (bbox or "").split(",") if x],
            }
            for bid, page, bbox in brows
        }
        return {
            cid: [box_by_block[b] for b in ids if b in box_by_block]
            for cid, ids in wanted.items()
        }

    def load_vectors(self) -> tuple[list[str], np.ndarray]:
        with self._lock:
            rows = self.conn.execute("SELECT chunk_id, vec FROM vectors").fetchall()
        if not rows:
            return [], np.zeros((0, 0), dtype=np.float32)
        ids = [r[0] for r in rows]
        dim = len(rows[0][1]) // 4
        mat = np.frombuffer(b"".join(r[1] for r in rows), dtype=np.float32).reshape(
            len(rows), dim
        )
        return ids, mat

    def close(self) -> None:
        self.conn.close()

# 摘要之前的内容一律不进入右侧栏：标题、作者、单位、邮箱、脚注
_EMAIL_RE = re.compile(r"[\w.\-]+@[\w\-]+\.[\w.\-]+")


def _trim_front_matter(items: list[dict], headings: list[str]) -> list[dict]:
    """去掉正文前的标题/作者/单位块，从摘要或第一个编号章节开始。

    找不到摘要标题时退化为"跳过前 3 个块"，避免把首页元数据全铺出来。
    """
    if not items:
        return items
    start = 0
    for i, h in enumerate(items):
        text = (h.get("text") or "").strip()
        low = text.lower()
        if low.startswith("abstract") or text.startswith("摘要"):
            start = i
            break
        if re.match(r"^\d{1,2}\s+[A-Z]", text):
            start = i
            break
    else:
        start = min(3, len(items))

    # 标题块自身也会出现在 blocks 里，右侧栏不需要重复一遍。
    # 注意两边的文本形态不一致：headings 存 "Introduction"，block 存 "1 Introduction"，
    # 所以比较前要剥掉编号。
    def _norm(text: str) -> str:
        return re.sub(r"^\s*\d+(?:\.\d+)*\s*", "", text.strip()).lower()

    heading_set = {_norm(h) for h in headings if h}
    kept = [
        it
        for it in items[start:]
        if not _EMAIL_RE.search(it["text"])
        and len(it["text"].strip()) >= 12
        and _norm(it["text"]) not in heading_set
    ]
    return kept or items
