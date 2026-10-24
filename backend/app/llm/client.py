"""DeepSeek 客户端。

只依赖 httpx，不引入任何 Agent 框架——理由见 PLAN.md：
框架内部的重试与解析逻辑我们改不动，而 DeepSeek 的 function calling
参数抖动必须由我们自己的降级策略兜住。

密钥只从环境变量读取，绝不落库、绝不入日志。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Iterator

import httpx

DEFAULT_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
CHAT_MODEL = os.environ.get("DEEPSEEK_CHAT_MODEL", "deepseek-chat")
REASONER_MODEL = os.environ.get("DEEPSEEK_REASONER_MODEL", "deepseek-reasoner")


class LLMError(RuntimeError):
    pass


@dataclass(slots=True)
class Message:
    role: str  # system | user | assistant
    content: str

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


def api_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise LLMError(
            "缺少 DEEPSEEK_API_KEY。请在项目根目录的 .env.local 中配置，"
            "该文件已在 .gitignore 中，不会进入仓库。"
        )
    return key


class DeepSeekClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 120.0,
        temperature: float = 0.2,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.temperature = temperature

    # ---------- 非流式 ----------
    def chat(
        self,
        messages: list[Message],
        model: str = CHAT_MODEL,
        temperature: float | None = None,
        max_tokens: int = 2048,
        json_mode: bool = False,
    ) -> str:
        payload = {
            "model": model,
            "messages": [m.to_dict() for m in messages],
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        resp = self._post(payload)
        try:
            return resp["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:  # pragma: no cover
            raise LLMError(f"响应结构异常: {resp}") from exc

    # ---------- 流式 ----------
    def stream(
        self,
        messages: list[Message],
        model: str = CHAT_MODEL,
        temperature: float | None = None,
        max_tokens: int = 2048,
    ) -> Iterator[str]:
        payload = {
            "model": model,
            "messages": [m.to_dict() for m in messages],
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        with httpx.Client(timeout=self.timeout) as client:
            with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            ) as response:
                if response.status_code >= 400:
                    raise LLMError(f"HTTP {response.status_code}: {response.read().decode()[:300]}")
                for line in response.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    piece = delta.get("content")
                    if piece:
                        yield piece

    # ---------- 内部 ----------
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {api_key()}",
            "Content-Type": "application/json",
        }

    def _post(self, payload: dict) -> dict:
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{self.base_url}/chat/completions", headers=self._headers(), json=payload
            )
            if resp.status_code >= 400:
                raise LLMError(f"HTTP {resp.status_code}: {resp.text[:300]}")
            return resp.json()


def has_key() -> bool:
    return bool(os.environ.get("DEEPSEEK_API_KEY", "").strip())
