"""抓取演示语料：注意力与预训练语言模型方向的一组论文。

为什么要一批而不是两篇：引用图谱需要 ≥10 篇才有结构，
单篇谈不上"基石节点"与"边缘衍生"。

用法：.venv\\Scripts\\python.exe scripts/fetch_corpus.py
"""
from __future__ import annotations

import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PDF_DIR = ROOT / "data" / "pdf"

# arXiv id : 论文名（用于人工核对）
CORPUS: dict[str, str] = {
    "1706.03762": "Attention Is All You Need",
    "1810.04805": "BERT",
    "2005.14165": "GPT-3",
    "1910.10683": "T5",
    "1907.11692": "RoBERTa",
    "1512.03385": "ResNet",
    "1409.0473": "Neural MT (attention 起源)",
    "1409.3215": "Seq2Seq",
    "1607.06450": "Layer Normalization",
    "1412.6980": "Adam",
    "1301.3781": "word2vec",
    "2010.11929": "ViT",
    "2205.14135": "FlashAttention",
    "2106.09685": "LoRA",
    "2001.04451": "Reformer",
    "1802.05365": "ELMo",
}


def fetch(arxiv_id: str, name: str, version: str = "") -> bool:
    dest = PDF_DIR / f"{arxiv_id}v{version}.pdf" if version else PDF_DIR / f"{arxiv_id}.pdf"
    if dest.exists() and dest.stat().st_size > 50_000:
        print(f"  已存在 {dest.name}")
        return True
    url = f"https://arxiv.org/pdf/{arxiv_id}"
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            data = urllib.request.urlopen(req, timeout=120).read()
            if len(data) < 50_000:
                raise ValueError(f"文件过小 {len(data)}")
            dest.write_bytes(data)
            print(f"  OK {dest.name}  {len(data) / 1e6:.1f}MB  ({name})")
            return True
        except Exception as exc:  # noqa: BLE001
            wait = 3 * (attempt + 1)
            print(f"  重试 {arxiv_id} ({attempt + 1}/3): {exc}")
            time.sleep(wait)
    print(f"  失败 {arxiv_id} {name}")
    return False


def main() -> int:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    ok = 0
    for arxiv_id, name in CORPUS.items():
        if fetch(arxiv_id, name):
            ok += 1
        time.sleep(1.2)  # arXiv 的礼貌间隔
    print(f"\n完成 {ok}/{len(CORPUS)}")
    return 0 if ok >= 10 else 1


if __name__ == "__main__":
    sys.exit(main())
