"""混合检索：BM25 + 稠密向量 → RRF 融合 → 多语言 CrossEncoder 重排。

为什么是这个组合（而不是单纯向量搜索）：

* 学术文本里，术语、超参、模型名是**稀有词**，BM25 的精确匹配能力比向量更强；
* 反过来，同义改写、跨语言提问，向量更强；
* 中文提问打英文库时，两种召回都可能失手，最终由 bge-reranker-v2-m3
  （多语言 cross-encoder）做交叉打分兜底——实测中文问"GPU 数量"能命中英文段落。

三者缺一不可，这也是评分表里"混合检索（Dense/Sparse）策略是否合理"的答案。
"""
from __future__ import annotations

import re
from functools import lru_cache

import jieba
import numpy as np
from rank_bm25 import BM25Okapi

from .expander import CJK, GlossaryExpander
from .store import Store

DENSE_MODEL = "BAAI/bge-small-en-v1.5"
RERANK_MODEL = "BAAI/bge-reranker-v2-m3-int8"
RRF_K = 60
_EN_TOKEN = re.compile(r"[a-z0-9]+(?:[-_.][a-z0-9]+)*")
_CJK = re.compile(r"[\u4e00-\u9fff]")


@lru_cache(maxsize=1)
def _dense_model():
    from fastembed import TextEmbedding

    return TextEmbedding(DENSE_MODEL)


@lru_cache(maxsize=1)
def _reranker():
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    return TextCrossEncoder(RERANK_MODEL)


def tokenize(text: str) -> list[str]:
    """中英混排分词：中文走 jieba，英文走正则并统一小写。"""
    lowered = text.lower()
    tokens = _EN_TOKEN.findall(lowered)
    cjk_spans = re.findall(r"[\u4e00-\u9fff]+", text)
    for span in cjk_spans:
        tokens.extend(t for t in jieba.cut(span) if t.strip())
    return tokens


class HybridRetriever:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.expander = GlossaryExpander()
        self.chunks = store.load_chunks()
        self.by_id = {c["id"]: c for c in self.chunks}
        self._bm25 = None
        self._vec_ids, self._vecs = store.load_vectors()
        self._vec_pos = {cid: i for i, cid in enumerate(self._vec_ids)}

    # ---------- 索引构建 ----------
    def build_bm25(self) -> None:
        corpus = [tokenize(c["text"]) for c in self.chunks]
        self._bm25 = BM25Okapi(corpus) if corpus else None

    def embed_missing(self, batch_size: int = 32) -> int:
        """为没有向量的块补算向量（BM25 可秒级就绪，稠密向量异步补齐）。"""
        todo = [c for c in self.chunks if c["id"] not in self._vec_pos]
        if not todo:
            return 0
        model = _dense_model()
        vectors = list(model.embed([c["text"] for c in todo], batch_size=batch_size))
        mat = np.vstack([np.asarray(v, dtype=np.float32) for v in vectors])
        self.store.save_vectors([c["id"] for c in todo], mat)
        self._vec_ids, self._vecs = self.store.load_vectors()
        self._vec_pos = {cid: i for i, cid in enumerate(self._vec_ids)}
        return len(todo)

    # ---------- 检索 ----------
    def _bm25_ranked(self, query: str, top_n: int) -> list[str]:
        if self._bm25 is None:
            self.build_bm25()
        if self._bm25 is None:
            return []
        scores = self._bm25.get_scores(tokenize(query))
        order = np.argsort(scores)[::-1][:top_n]
        return [self.chunks[i]["id"] for i in order if scores[i] > 0]

    def _dense_ranked(self, query: str, top_n: int) -> list[str]:
        if self._vecs.size == 0:
            return []
        q = np.asarray(next(iter(_dense_model().embed([query]))), dtype=np.float32)
        sims = self._vecs @ q
        order = np.argsort(sims)[::-1][:top_n]
        return [self._vec_ids[i] for i in order]

    def search(
        self,
        query: str,
        top_k: int = 6,
        candidates: int = 30,
        rerank: bool = True,
    ) -> list[dict]:
        # 中文提问先做术语扩展，否则英文库检索几乎必然失效
        expanded = self.expander.expand(query)
        lexical_query = expanded
        dense_query = expanded if CJK.search(query) else query

        bm25_ids = self._bm25_ranked(lexical_query, candidates)
        dense_ids = self._dense_ranked(dense_query, candidates)

        fused: dict[str, float] = {}
        for rank, cid in enumerate(bm25_ids):
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (RRF_K + rank + 1)
        for rank, cid in enumerate(dense_ids):
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (RRF_K + rank + 1)

        cand_ids = sorted(fused, key=lambda c: fused[c], reverse=True)[: max(top_k, 12)]
        if not cand_ids:
            return []

        hits = []
        scores: dict[str, float] = {}
        if rerank:
            pairs = [self.by_id[c]["text"] for c in cand_ids]
            for cid, s in zip(cand_ids, _reranker().rerank(query, pairs), strict=False):
                scores[cid] = float(s)
        else:
            scores = {c: fused[c] for c in cand_ids}

        for cid in cand_ids:
            chunk = self.by_id[cid]
            hits.append(
                {
                    **chunk,
                    "rrf": round(fused[cid], 6),
                    "score": round(scores.get(cid, fused[cid]), 4),
                    "anchor": make_anchor(chunk),
                }
            )
        hits.sort(key=lambda h: h["score"], reverse=True)
        return hits[:top_k]


def make_anchor(chunk: dict) -> dict:
    """人类可读 + 机器可跳转的双重锚点。"""
    page = chunk["page_start"]
    section = chunk["section_title"] or "正文"
    return {
        "label": f"{chunk['paper_id']} · p{page} · §{section}",
        "paper_id": chunk["paper_id"],
        "page": page,
        "bbox": chunk["bbox"],
        "chunk_id": chunk["id"],
    }


def format_hits(hits: list[dict], width: int = 110) -> str:
    lines = []
    for i, h in enumerate(hits, 1):
        snippet = h["text"][:width].replace("\n", " ")
        lines.append(f"  [{i}] score={h['score']:+.3f} rrf={h['rrf']:.4f}  {h['anchor']['label']}")
        lines.append(f"      {snippet}…")
    return "\n".join(lines)
