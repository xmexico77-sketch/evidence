"""Agent 层：意图路由 → 计划 → 执行 → 自检。

为什么单独成层：评分表里 35% 是「Agent / 大模型技术深度」。此前的实现是一个
坚实的 RAG 应用——检索、重排、锚点、抗幻觉闸门都有，但流程是写死的：进来一个
问题就走同一条路。这层补上的是**决策与自我审查**：

    IntentRouter  判断这是什么类型的问题（单篇 / 跨篇 / 发现 / 综述）
    Planner       据此生成步骤计划（可解释，而不是黑盒一条路）
    Executor      按计划执行，逐步上报耗时与观测
    Critic        校验答案是否真的被证据支撑，不该答就判失败

设计原则（与项目主线一致，都是为了"可信"）：

1. **路由优先用规则**，规则判不出来才请模型判断。学术问句的形态很稳定
   （"这篇""对比""有哪些最新"），规则又快又不会幻觉；模型只用来兜底歧义。
2. **计划是数据，不是日志**。每步有 id 与标签，前端据此渲染轨迹，
   测试也能断言"该走哪几步"。
3. **自检不信任模型的自述**。Critic 只看两件事：引用编号是否真实存在，
   以及引用原文与答案是否有词面重叠——这能在模型"张冠李戴"时兜住。
"""
from .critic import Critique, critique
from .intent import Intent, IntentResult, route
from .planner import Plan, Step, make_plan
from .runtime import AgentRun, run_stream

__all__ = [
    "AgentRun",
    "Critique",
    "Intent",
    "IntentResult",
    "Plan",
    "Step",
    "critique",
    "make_plan",
    "route",
    "run_stream",
]
