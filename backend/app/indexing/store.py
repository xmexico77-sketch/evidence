"""存储层：SQLite（WAL）存元数据与块，向量单独存 npz。

单机零运维的选择，理由见 PLAN.md：评审只需 docker compose up，
不引入 Postgres/Milvus 来增加质量风险。所有写入走单一连接 + WAL，
够单人演示规模（万级块）。
"""
from __future__ import annotations

import json
import sqlite3
import threading
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

    def load_refs(self) -> dict[str, list[tuple[int, str]]]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT paper_id, ref_index, text FROM refs ORDER BY paper_id, ref_index"
            ).fetchall()
        out: dict[str, list[tuple[int, str]]] = {}
        for paper_id, idx, text in rows:
            out.setdefault(paper_id, []).append((idx, text))
        return out

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
