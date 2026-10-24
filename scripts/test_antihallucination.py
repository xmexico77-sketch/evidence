"""反幻觉 Guardrails 的确定性测试（用替身模型，不消耗 API 额度）。

这是项目的技术主线，必须能在没有 API Key 的情况下被反复验证。
用法：.venv\\Scripts\\python.exe scripts\\test_antihallucination.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.llm.mock import ScriptedLLM  # noqa: E402
from app.rag.answerer import (  # noqa: E402
    Evidence,
    GroundedAnswerer,
    numeric_consistency,
    parse_markers,
    validate_markers,
)

FAKE_HITS = [
    {
        "id": "1706.03762v1#c0001",
        "paper_id": "1706.03762v1",
        "index": 1,
        "text": "We trained our models on one machine with 8 NVIDIA P100 GPUs.",
        "section_path": "5 Training > 5.2 Hardware and Schedule",
        "section_title": "Hardware and Schedule",
        "page_start": 7,
        "page_end": 7,
        "bbox": [100.0, 200.0, 500.0, 260.0],
        "score": 5.2,
    },
    {
        "id": "1706.03762v1#c0002",
        "paper_id": "1706.03762v1",
        "index": 2,
        "text": "We used the Adam optimizer with beta1 = 0.9 and beta2 = 0.98 [20].",
        "section_path": "5 Training > 5.3 Optimizer",
        "section_title": "Optimizer",
        "page_start": 7,
        "page_end": 7,
        "bbox": [100.0, 300.0, 500.0, 340.0],
        "score": 4.1,
    },
]


class FakeRetriever:
    def __init__(self, hits):
        self.hits = hits

    def search(self, question: str, top_k: int = 5, **kwargs):  # noqa: ANN001, ARG002
        return self.hits[:top_k]


results: list[tuple[bool, str, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((cond, name, detail))


def main() -> int:
    ev = [Evidence(i + 1, h) for i, h in enumerate(FAKE_HITS)]

    # 1) 标记解析
    check("解析单标记", parse_markers("答案是 x [E1]。") == [1])
    check("解析多标记", parse_markers("两者相比 [E1][E2] 有差异。") == [1, 2])
    check("无标记返回空", parse_markers("没有标记的回答。") == [])

    # 2) 越界编号必须被识别
    valid, invalid = validate_markers("事实A [E1]，事实B [E9]。", ev)
    check("越界编号被判无效", valid == [1] and invalid == [9], f"valid={valid} invalid={invalid}")

    # 3) 回归：论文自身的参考文献标记 [32] 不得被当成证据编号
    text = "我们采用标签平滑 ϵls = 0.1 [32] [E1]。"
    valid, invalid = validate_markers(text, ev)
    check("论文自身 [32] 不干扰校验", valid == [1] and invalid == [], f"valid={valid} invalid={invalid}")
    check("不误解析普通方括号", parse_markers("见文献 [32] 与 [20]。") == [])

    # 4) 正常路径：有编号 -> grounded
    ans = GroundedAnswerer(
        FakeRetriever(FAKE_HITS), ScriptedLLM(["训练使用 8 块 P100 GPU [E1]。"])
    ).ask("用了多少 GPU？")
    check("正常路径 grounded", ans.grounded and not ans.repaired)
    check("引用数量正确", len(ans.citations) == 1, f"citations={len(ans.citations)}")
    check("引用带锚点页码", ans.citations[0]["anchor"]["page"] == 7, str(ans.citations[0]["anchor"]))
    check("引用带 bbox", len(ans.citations[0]["anchor"]["bbox"]) == 4)
    check("标记格式为 E 型", ans.citations[0]["marker"] == "[E1]", ans.citations[0]["marker"])

    # 5) 首次无编号 -> 触发修复并成功
    ans = GroundedAnswerer(
        FakeRetriever(FAKE_HITS),
        ScriptedLLM(["它用了 8 块 GPU。", "它用了 8 块 P100 GPU [E1]。"]),
    ).ask("用了多少 GPU？")
    check("无编号触发修复", ans.repaired, f"repaired={ans.repaired}")
    check("修复后 grounded", ans.grounded)

    # 6) 编造编号 -> 不通过（修复也失败）
    ans = GroundedAnswerer(
        FakeRetriever(FAKE_HITS),
        ScriptedLLM(["它用了 8 块 GPU [E7]。", "它用了 8 块 GPU [E8]。"]),
    ).ask("用了多少 GPU？")
    check("编造编号不通过", not ans.grounded, f"grounded={ans.grounded}")
    check("记录无效编号", ans.invalid_markers == [7], str(ans.invalid_markers))

    # 7) 证据不足 -> 不得伪装成有据
    ans = GroundedAnswerer(
        FakeRetriever(FAKE_HITS), ScriptedLLM(["证据不足：证据未涉及预训练数据规模。"])
    ).ask("预训练用了多少数据？")
    check("证据不足被识别", ans.insufficient and not ans.grounded)

    # 8) 空知识库
    ans = GroundedAnswerer(FakeRetriever([]), ScriptedLLM(["不该被调用"])).ask("任意问题")
    check("空检索直接拒答", ans.insufficient and ans.evidence_used == 0)

    # 8b) 相关性闸门：证据相关度过低时必须拒答，而不是拿无关原文配合法锚点
    weak_hits = [dict(FAKE_HITS[0], score=-7.5)]
    ans = GroundedAnswerer(FakeRetriever(weak_hits), ScriptedLLM(["作者拿过两次图灵奖 [E1]。"])).ask(
        "这篇论文的作者获得过几次图灵奖？"
    )
    check("低相关度拒答", ans.insufficient, f"insufficient={ans.insufficient}")
    check("低相关度不产生答案", "证据不足" in ans.answer, ans.answer[:60])
    check("低相关度记录置信度", ans.confidence == -7.5, str(ans.confidence))

    # 8c) 相关性足够时闸门放行
    strong_hits = [dict(FAKE_HITS[0], score=2.2)]
    ans = GroundedAnswerer(FakeRetriever(strong_hits), ScriptedLLM(["8 块 P100 [E1]。"])).ask("多少 GPU？")
    check("高相关度放行", ans.grounded, f"grounded={ans.grounded}")

    # 9) 数字一致性：证据里没有 16，应报可疑
    suspicious = numeric_consistency("模型用了 16 块 GPU [E1]。", ev)
    check("可疑数字被抓出", "16" in suspicious, f"suspicious={suspicious}")
    clean = numeric_consistency("模型用了 8 块 GPU [E1]。", ev)
    check("正确数字不误报", clean == [], f"suspicious={clean}")

    passed = sum(1 for ok, _, _ in results if ok)
    for ok, name, detail in results:
        mark = "PASS" if ok else "FAIL"
        extra = f"  ({detail})" if detail and not ok else ""
        print(f"[{mark}] {name}{extra}")
    print(f"\n{passed}/{len(results)} 项通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
