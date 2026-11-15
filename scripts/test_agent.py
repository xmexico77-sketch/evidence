"""Agent 层验收：路由、计划、自检、以及端到端事件流。

为什么单独一个测试：这层是评分表 35%（Agent 技术深度）的落点，
它必须能证明"真的在决策与自审"，而不是包装话术。

覆盖：
1. 路由：四种意图的规则判定 + 作用域优先 + 规则判不出来的兜底；
2. 计划：每个意图的步骤 id 与顺序，且必含检索/生成/自检；
3. 自检：幽灵编号、无标注、张冠李戴、拒答四种情形的判定；
4. 端到端：/api/ask/stream 的事件序列包含 route/plan/step/answer/critic/done。

用法：.venv\\Scripts\\python.exe scripts\\test_agent.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.agent import critique, make_plan, route  # noqa: E402
from app.agent.intent import Intent  # noqa: E402

results: list[tuple[bool, str, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((cond, name, detail))


class FakeLLM:
    """只回一个词的假模型，用来测路由兜底。"""

    def __init__(self, word: str) -> None:
        self.word = word
        self.calls = 0

    def chat(self, messages) -> str:  # noqa: ANN001
        self.calls += 1
        return self.word


def main() -> int:
    # ---------- 1. 路由 ----------
    r = route("Attention Is All You Need 里用了几个注意力头？", paper_id="1706.03762v7")
    check("给了 paper_id → 单篇问答", r.intent is Intent.PAPER_QA and r.method == "scope", r.to_dict())

    r = route("对比 BERT 和 RoBERTa 的预训练策略差异")
    check("对比类关键词 → COMPARE", r.intent is Intent.COMPARE, r.to_dict())

    r = route("最近有哪些关于长上下文的高效注意力工作？")
    check("发现类关键词 → DISCOVER", r.intent is Intent.DISCOVER, r.to_dict())

    r = route("Transformer 架构的演进脉络是怎样的？")
    check("综述类关键词 → REVIEW", r.intent is Intent.REVIEW, r.to_dict())

    r = route("Adam 的默认学习率是多少")
    check("无特征问题 → 默认整库问答", r.intent is Intent.LIBRARY_QA and r.method == "default", r.to_dict())

    fake = FakeLLM("compare")
    r = route("这两个方法哪个更好", llm=fake)   # 规则判不出（"更好"不在对比正则里）
    check("规则判不出时请模型兜底", r.method == "llm" and r.intent is Intent.COMPARE, r.to_dict())
    check("兜底时调用了模型", fake.calls == 1, f"calls={fake.calls}")

    fake2 = FakeLLM("paper")
    r = route("这个方法的具体实现细节", llm=fake2)
    check("模型判单篇但无 paper_id → 降级整库", r.intent is Intent.LIBRARY_QA and r.method == "llm", r.to_dict())

    class BoomLLM:
        def chat(self, messages):  # noqa: ANN001, ANN202
            raise RuntimeError("模型挂了")

    r = route("这个方法的具体实现细节", llm=BoomLLM())
    check("模型异常时不影响路由", r.intent is Intent.LIBRARY_QA, r.to_dict())

    # ---------- 2. 计划 ----------
    for intent in (Intent.PAPER_QA, Intent.LIBRARY_QA, Intent.COMPARE, Intent.DISCOVER, Intent.REVIEW):
        plan = make_plan(intent)
        ids = [s.id for s in plan.steps]
        check(f"计划[{intent.value}] 含检索/生成/自检",
              {"answer", "critic"} <= set(ids) and any("retrieve" in i or "检索" in i for i in ids), str(ids))
        check(f"计划[{intent.value}] 首步是路由", ids[0] == "route", str(ids))

    plan = make_plan(Intent.COMPARE, scoped=True)
    check("scoped 时插入收窄范围步骤", "scope" in [s.id for s in plan.steps], str([s.id for s in plan.steps]))

    # ---------- 3. 自检 ----------
    cites = [
        {"marker": 1, "snippet": "We train the model on 8 NVIDIA P100 GPUs for 3.5 days."},
        {"marker": 2, "snippet": "Adam uses beta1 = 0.9 and beta2 = 0.999."},
    ]
    good_answer = "模型训练用了 8 块 NVIDIA P100 GPU [E1]，优化器 beta1 取 0.9 [E2]。"
    c = critique(good_answer, cites)
    check("有据答案自检通过", c.ok, c.to_dict())

    c = critique("模型训练用了 8 块 GPU [E9]。", cites)
    check("幽灵编号被判失败", not c.ok and any("不存在" in i for i in c.issues), c.to_dict())

    c = critique("模型训练用了 8 块 GPU。", cites)
    check("无标注被判失败", not c.ok and any("没有" in i for i in c.issues), c.to_dict())

    # 张冠李戴：讲的是图像分类，引用却是 Adam 超参
    c = critique("ResNet 在 ImageNet 上取得 top-5 错误率 3.57% [E2]。", cites)
    check("张冠李戴被判失败", not c.ok and any("重合不足" in i for i in c.issues), c.to_dict())

    c = critique("证据不足：知识库中没有相关依据。", [], insufficient=True)
    check("拒答视为合法结局", c.ok and c.checks.get("verdict") == "refusal", c.to_dict())

    c = critique("证据不足，但参考文献 [E1] 提到过。", [], insufficient=True)
    check("拒答却带幽灵编号被判失败", not c.ok, c.to_dict())

    # ---------- 4. 端到端事件流 ----------
    try:
        from fastapi.testclient import TestClient  # noqa: PLC0415

        from app.main import app  # noqa: PLC0415

        client = TestClient(app)
        events: list[dict] = []
        with client.stream("POST", "/api/ask/stream",
                           json={"question": "Attention 用了几个注意力头？", "top_k": 3}) as resp:
            check("SSE 返回 200", resp.status_code == 200, str(resp.status_code))
            for line in resp.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                try:
                    events.append(json.loads(line[5:].strip()))
                except json.JSONDecodeError:
                    continue
        types = [e.get("type") for e in events]
        check("事件流含 route", "route" in types, str(types))
        check("事件流含 plan", "plan" in types, str(types))
        check("事件流含 step", types.count("step") >= 2, str(types))
        check("事件流含 answer", "answer" in types, str(types))
        check("事件流含 critic", "critic" in types, str(types))
        check("事件流以 done 收尾", types and types[-1] == "done", str(types[-3:]))
        steps = [e for e in events if e.get("type") == "step"]
        check("每步都带耗时", all("elapsed_ms" in s for s in steps), str([s.get("id") for s in steps]))
    except Exception as exc:  # noqa: BLE001
        check("端到端事件流", False, f"{type(exc).__name__}: {exc}")

    ok = sum(1 for c_, _, _ in results if c_)
    for cond, name, detail in results:
        print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if not cond and detail else ""))
    print(f"\n{ok}/{len(results)} 项通过")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
