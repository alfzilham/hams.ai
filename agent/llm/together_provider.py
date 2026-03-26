"""
Together AI LLM Provider
"""

from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator

import httpx
from loguru import logger

from agent.llm.base import BaseLLM, LLMResponse


class TogetherLLM(BaseLLM):
    """
    Integration with Together AI (OpenAI-compatible API).
    Good for Qwen, Llama, Mixtral models.
    """

    BASE_URL = "https://api.together.xyz/v1/chat/completions"

    def __init__(
        self,
        model: str = "Qwen/Qwen2.5-Coder-32B-Instruct",
        max_tokens: int = 4096,
        temperature: float = 0.0,
        api_key: str | None = None,
    ) -> None:
        super().__init__(model, max_tokens, temperature)
        self.api_key = api_key or os.environ.get("TOGETHER_API_KEY")
        if not self.api_key:
            raise ValueError("TOGETHER_API_KEY environment variable is required")

    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stop_sequences: list[str] | None = None,
    ) -> LLMResponse:
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
            
        if stop_sequences:
            payload["stop"] = stop_sequences

        logger.debug(f"[TogetherLLM] Generating with {self.model}")

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(self.BASE_URL, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        choice = data["choices"][0]
        message = choice.get("message", {})
        
        content = message.get("content") or ""
        tool_calls = message.get("tool_calls")

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            raw_response=data,
        )

    async def generate_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[str]:
        # Basic fallback, no actual streaming implemented yet
        resp = await self.generate(messages, tools)
        yield resp.content
