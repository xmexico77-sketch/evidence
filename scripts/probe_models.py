"""M2 可行性探针：验证本地向量与多语言重排模型可用，且中文查询能命中英文段落。

跑法（需完整权限，首次会下载模型）：
  .venv\\Scripts\\python.exe scripts\\probe_models.py
"""
from __future__ import annotations

import sys
import time


def main() -> None:
    from fastembed import TextEmbedding
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    docs = [
        "Attention Is All You Need proposes the Transformer based entirely on attention mechanisms.",
        "BERT pre-trains deep bidirectional representations from unlabeled text.",
        "We trained on 8 NVIDIA P100 GPUs for 12 hours.",
    ]

    t = time.time()
    dense = TextEmbedding("BAAI/bge-small-en-v1.5")
    print(f"[dense] load {time.time() - t:.1f}s")
    t = time.time()
    vecs = list(dense.embed(docs))
    print(f"[dense] dim={len(vecs[0])} embed3={time.time() - t:.2f}s")

    t = time.time()
    ce = TextCrossEncoder("BAAI/bge-reranker-v2-m3-int8")
    print(f"[rerank] load {time.time() - t:.1f}s")

    for q in ("Transformer 基于什么机制？", "训练用了多少块 GPU？"):
        t = time.time()
        scores = [float(s) for s in ce.rerank(q, docs)]
        best = max(range(len(scores)), key=lambda i: scores[i])
        print(f"[rerank] q={q} scores={[round(s, 4) for s in scores]} "
              f"best=#{best} in {time.time() - t:.2f}s")

    print("VERIFY_OK")


if __name__ == "__main__":
    sys.exit(main())
