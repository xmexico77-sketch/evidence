"""执行器：按计划跑完，并把每一步的观测与耗时作为事件吐出来。

与"把日志打印出来"的区别：事件是**结构化**的，前端据此渲染轨迹面板，
测试据此断言流程。每个事件都带 type，向前兼容——前端不认识新 type 可以直接忽略。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterator

from ..rag.answerer import AnswerResult, GroundedAnswerer
from ..indexing.retriever import HybridRetriever
from .critic import critique
from .intent import route
from .planner import make_plan


@dataclass(slots=True)
class AgentRun:
    """一次 Agent 执行的上下文与结果。"""

    question: str
    paper_id: str | None = None
    top_k: int = 5
    intent: str = ""
    plan: list[dict] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)
    result: AnswerResult | None = None
    critique: dict | None = None
    elapsed_ms: int = 0


def _event(type_: str, **payload: Any) -> dict:
    return {"type": type_, **payload}


def run_stream(
    question: str,
    retriever: HybridRetriever,
    answerer: GroundedAnswerer,
    llm=None,                    # noqa: ANN001 —— 仅用于意图兜底
    paper_id: str | None = None,
    top_k: int = 5,
) -> Iterator[dict]:
    """执行一次 Agent 流程，逐步 yield 事件（供 SSE 直接下发）。

    事件序列：
        route    意图与判定依据
        plan     步骤计划
        step     单步开始/结束（含耗时与观测）
        answer   答案正文
        citations 锚点
        critic   自检结论
        done     总耗时
    """
    t_start = time.perf_counter()
    steps_done: list[dict] = []

    def emit_step(sid: str, label: str, ok: bool, elapsed_ms: int, observation: str = "") -> dict:
        rec = {
            "id": sid,
            "label": label,
            "ok": ok,
            "elapsed_ms": elapsed_ms,
            "observation": observation,
        }
        steps_done.append(rec)
        return _event("step", **rec)

    # ---- 1. 路由 ----
    t = time.perf_counter()
    r = route(question, paper_id=paper_id, llm=llm)
    yield _event("route", **r.to_dict())
    yield emit_step("route", "识别意图", True, int((time.perf_counter() - t) * 1000),
                    f"{r.intent.value}（{r.method}：{r.reason}）")

    # ---- 2. 计划 ----
    plan = make_plan(r.intent, scoped=bool(paper_id))
    yield _event("plan", **plan.to_dict())

    # ---- 3. 检索 ----
    t = time.perf_counter()
    scope = {paper_id} if paper_id else None
    hits: list[dict] = []
    try:
        hits = retriever.search(question, top_k=top_k, paper_filter=scope)
        obs = f"命中 {len(hits)} 段" + (
            f"，最高分 {max(float(h.get('score') or 0) for h in hits):.3f}" if hits else ""
        )
        yield emit_step("retrieve", "混合检索", True, int((time.perf_counter() - t) * 1000), obs)
    except Exception as exc:  # noqa: BLE001 —— 检索失败也要如实上报，不能假装成功
        yield emit_step("retrieve", "混合检索", False, int((time.perf_counter() - t) * 1000),
                        f"失败：{type(exc).__name__}")
        yield _event("error", message=f"检索失败：{exc}")
        yield _event("done", elapsed_ms=int((time.perf_counter() - t_start) * 1000))
        return

    # ---- 4. 生成 ----
    t = time.perf_counter()
    try:
        result = answerer.ask(question, top_k=top_k, paper_filter=scope, hits=hits)
    except Exception as exc:  # noqa: BLE001
        yield emit_step("answer", "生成答案", False, int((time.perf_counter() - t) * 1000),
                        f"失败：{type(exc).__name__}")
        yield _event("error", message=f"生成失败：{exc}")
        yield _event("done", elapsed_ms=int((time.perf_counter() - t_start) * 1000))
        return

    yield emit_step(
        "answer", "生成带锚点的答案", True, int((time.perf_counter() - t) * 1000),
        ("拒答" if result.insufficient else f"标注 {len(result.citations)} 处")
        + ("，已自动修复编号" if result.repaired else ""),
    )
    yield _event("answer", delta=result.answer)
    yield _event(
        "citations",
        grounded=result.grounded,
        insufficient=result.insufficient,
        repaired=result.repaired,
        invalid_markers=result.invalid_markers,
        confidence=result.confidence,
        citations=result.citations,
    )

    # ---- 5. 自检 ----
    t = time.perf_counter()
    c = critique(result.answer, result.citations, result.insufficient)
    yield _event("critic", **c.to_dict())
    yield emit_step(
        "critic", "自检证据一致性", c.ok, int((time.perf_counter() - t) * 1000),
        "通过" if c.ok else f"{len(c.issues)} 项问题",
    )

    yield _event(
        "done",
        elapsed_ms=int((time.perf_counter() - t_start) * 1000),
        steps=steps_done,
    )
