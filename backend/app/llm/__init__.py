"""LLM 层：DeepSeek 客户端、Prompt 模板、离线替身。"""
from .client import CHAT_MODEL, REASONER_MODEL, DeepSeekClient, LLMError, Message, has_key
from .mock import EchoLLM, ExtractiveLLM, HandlerLLM, ScriptedLLM
from .prompts import ALL_PROMPTS, GROUNDED_ANSWER

__all__ = [
    "CHAT_MODEL",
    "REASONER_MODEL",
    "DeepSeekClient",
    "LLMError",
    "Message",
    "has_key",
    "EchoLLM",
    "ExtractiveLLM",
    "HandlerLLM",
    "ScriptedLLM",
    "ALL_PROMPTS",
    "GROUNDED_ANSWER",
]
