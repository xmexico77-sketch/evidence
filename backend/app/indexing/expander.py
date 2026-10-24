"""查询扩展：把中文提问映射到英文论文的术语空间。

为什么必须有这一层：

英文 dense 模型（bge-small-en）对中文 query 的向量几乎无意义，
BM25 又切不出对应的英文词。实测"标签平滑"查不到 "label smoothing"，
"注意力头"查不到 "attention heads"——而正确段落确实在库里。

三级扩展策略（按可用性递降）：
  1. LLM 扩展（有 DeepSeek Key 时）——最灵活，能处理任意领域术语
  2. 术语表扩展（本模块，离线可用）——覆盖常见学术/深度学习术语
  3. 原样查询——保底

注意：扩展只用于"召回"，最终排序仍由多语言 CrossEncoder 决定，
所以术语表不精确也不会造成错误答案，只会影响召回率。
"""
from __future__ import annotations

import re

CJK = re.compile(r"[\u4e00-\u9fff]")

# 学术/深度学习高频术语：中文 -> 英文（论文中可能出现的原词）
GLOSSARY: dict[str, str] = {
    "标签平滑": "label smoothing",
    "注意力头": "attention heads",
    "多头注意力": "multi-head attention",
    "自注意力": "self-attention",
    "注意力机制": "attention mechanism",
    "注意力": "attention",
    "位置编码": "positional encoding",
    "位置前馈": "position-wise feed-forward",
    "前馈网络": "feed-forward network",
    "残差连接": "residual connection",
    "层归一化": "layer normalization",
    "批归一化": "batch normalization",
    "超参数": "hyperparameter",
    "优化器": "optimizer",
    "学习率": "learning rate",
    "学习率预热": "warmup",
    "梯度": "gradient",
    "梯度裁剪": "gradient clipping",
    "正则化": "regularization",
    "丢弃": "dropout",
    "训练": "training",
    "推理": "inference",
    "微调": "fine-tuning",
    "预训练": "pre-training",
    "数据集": "dataset",
    "语料": "corpus",
    "批次": "batch",
    "编码器": "encoder",
    "解码器": "decoder",
    "卷积": "convolution",
    "循环神经网络": "recurrent neural network",
    "长短期记忆": "LSTM",
    "门控循环": "gated recurrent",
    "机器翻译": "machine translation",
    "英德": "English-to-German",
    "英法": "English-to-French",
    "双语评估": "BLEU",
    "困惑度": "perplexity",
    "准确率": "accuracy",
    "损失函数": "loss function",
    "参数": "parameter",
    "参数量": "number of parameters",
    "权重": "weight",
    "偏差": "bias",
    "层数": "layers",
    "维度": "dimension",
    "复杂度": "complexity",
    "计算复杂度": "computational complexity",
    "显存": "GPU memory",
    "显卡": "GPU",
    "模型并行": "model parallel",
    "消融实验": "ablation",
    "基线": "baseline",
    "鲁棒性": "robustness",
    "泛化": "generalization",
    "蒸馏": "distillation",
    "对比学习": "contrastive learning",
    "检索": "retrieval",
    "生成": "generation",
    "幻觉": "hallucination",
    "引用": "citation",
    "参考文献": "references",
    "摘要": "abstract",
    "数据集划分": "data split",
    "词表": "vocabulary",
    "分词": "tokenization",
    "字节对编码": "byte-pair encoding",
    "断言": "claim",
    "消融": "ablation study",
    "未来工作": "future work",
    "局限": "limitations",
}


class GlossaryExpander:
    """离线查询扩展：最长优先匹配，避免"注意力"抢先匹配"多头注意力"。"""

    def __init__(self, glossary: dict[str, str] | None = None) -> None:
        self.glossary = dict(glossary or GLOSSARY)
        self._keys = sorted(self.glossary, key=len, reverse=True)

    def terms(self, query: str) -> list[str]:
        if not CJK.search(query):
            return []
        found: list[str] = []
        consumed: list[tuple[int, int]] = []
        for key in self._keys:
            for match in re.finditer(re.escape(key), query):
                span = (match.start(), match.end())
                if any(not (span[1] <= s or span[0] >= e) for s, e in consumed):
                    continue  # 已被更长的术语覆盖
                consumed.append(span)
                term = self.glossary[key]
                if term not in found:
                    found.append(term)
        return found

    def expand(self, query: str) -> str:
        terms = self.terms(query)
        if not terms:
            return query
        return f"{query} {' '.join(terms)}"


class LLMExpander:
    """占位：接入 DeepSeek 后启用，支持任意领域术语与同义改写。"""

    def __init__(self, client) -> None:  # noqa: ANN001 - 避免循环依赖
        self.client = client

    def expand(self, query: str) -> str:  # pragma: no cover - 需要 API Key
        return self.client.expand_query(query)
