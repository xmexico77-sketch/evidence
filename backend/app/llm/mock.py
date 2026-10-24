"""离线替身模型：用于在没有 API Key 的情况下验证全链路与 Guardrails。

两个替身各有用途：
* ScriptedLLM  —— 按脚本返回，用于反幻觉规则的确定性测试；
* ExtractiveLLM —— 从证据里抽句子并标编号，用于无 Key 时跑通端到端演示。
"""
from __future__ import annotations

import re
from typing import Callable

EVIDENCE_HEAD = re.compile(r"^\[E(\d{1,2})\]\s*来源：(.+)$", re.M)
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


class ScriptedLLM:
    """按顺序吐出预设回答；用完则重复最后一条。"""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[list] = []

    def chat(self, messages, **kwargs) -> str:  # noqa: ANN001, ARG002
        self.calls.append(messages)
        if not self.responses:
            return ""
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


class HandlerLLM:
    """用回调决定回答，便于测试不同分支。"""

    def __init__(self, handler: Callable[[list], str]) -> None:
        self.handler = handler
        self.calls: list[list] = []

    def chat(self, messages, **kwargs) -> str:  # noqa: ANN001, ARG002
        self.calls.append(messages)
        return self.handler(messages)


class ExtractiveLLM:
    """抽取式替身：不编造，只从证据里挑与问题词重合度最高的句子并标注编号。"""

    def chat(self, messages, **kwargs) -> str:  # noqa: ANN001, ARG002
        user = next((m.content for m in messages if m.role == "user"), "")
        if "【原回答】" in user:  # 修复提示：直接原样返回，交给上层判失败
            return "证据不足：无法从证据中重写。"
        question = ""
        if "【问题】" in user:
            question = user.split("【问题】", 1)[1].split("【证据】", 1)[0].strip()

        evidence: dict[int, str] = {}
        current = None
        for line in user.splitlines():
            m = EVIDENCE_HEAD.match(line.strip())
            if m:
                current = int(m.group(1))
                evidence[current] = ""
                continue
            if current is not None and line.strip():
                evidence[current] += line.strip() + " "

        if not evidence:
            return "证据不足：没有可用证据。"

        q_terms = {t for t in re.split(r"[\s，。？！,?]+", question) if len(t) >= 2}
        best_idx, best_sent, best_hit = None, "", -1
        for idx, text in evidence.items():
            for sent in _SENT_SPLIT.split(text):
                hits = sum(1 for t in q_terms if t in sent)
                if hits > best_hit and len(sent) > 30:
                    best_idx, best_sent, best_hit = idx, sent.strip(), hits

        if best_idx is None:
            return "证据不足：检索到的内容与问题不匹配。"
        return f"根据证据，{best_sent} [E{best_idx}]"


class EchoLLM:
    """最小替身：把最后一条 user 消息原样回显，用于接口连通性测试。"""

    def chat(self, messages, **kwargs) -> str:  # noqa: ANN001, ARG002
        return next((m.content for m in reversed(messages) if m.role == "user"), "")
