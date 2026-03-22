"""
HAMS-MAX LLM Provider — wraps hams-max-api-production.up.railway.app
Implements BaseLLM interface agar bisa dipakai di LLMRouter.
"""

from __future__ import annotations

import os
from typing import Any, AsyncIterator

import httpx
from loguru import logger

from agent.llm.base import BaseLLM, LLMResponse

HAMS_MAX_BASE = "https://hams-max-api-production.up.railway.app"

HAMS_MAX_MODELS = {
    "groq":       "llama-3.3-70b-versatile",
    "qwen":       "qwen3.5-122b-a10b",
    "deepseek":   "deepseek-v3.2",
    "nemotron":   "nemotron-3-super-120b-a12b",
    "kimi-think": "kimi-k2-instruct",
    "mistral":    "mistral-small-4-119b",
    "qwen397b":   "qwen3.5-397b-a17b",
    "kimi":       "kimi-k2.5",
    "minimax":    "minimax-m2.5",
    "glm":        "glm5",
    "step":       "step-3.5-flash",
}


class HamsMaxLLM(BaseLLM):
    """
    LLM provider yang memanggil HAMS-MAX API.

    Usage::
        llm = HamsMaxLLM(model="groq")       # Groq LLaMA 3.3 70B
        llm = HamsMaxLLM(model="deepseek")   # DeepSeek V3.2
        llm = HamsMaxLLM(model="nemotron")   # Nemotron Super 120B
    """

    def __init__(
        self,
        model: str = "groq",
        max_tokens: int = 2048,
        temperature: float = 0.7,
    ) -> None:
        model_id = HAMS_MAX_MODELS.get(model, HAMS_MAX_MODELS["groq"])
        super().__init__(model=model_id, max_tokens=max_tokens, temperature=temperature)
        self._model_key = model
        self._api_key = os.environ.get("HAMS_MAX_API_KEY", "")
        self._provider = "groq" if model == "groq" else "nvidia"

        if not self._api_key:
            raise RuntimeError("HAMS_MAX_API_KEY environment variable is not set.")

        logger.info(f"[hams-max] provider={self._provider} model={self._model_key}")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _build_payload(self, messages: list[dict], system: str | None = None) -> dict:
        # Ambil user message terakhir
        user_message = ""
        history = []
        for msg in messages:
            if msg["role"] in ("user", "assistant"):
                history.append({"role": msg["role"], "content": msg["content"]})

        if history and history[-1]["role"] == "user":
            user_message = history[-1]["content"]
            history = history[:-1]

        return {
            "message": user_message,
            "session_id": "hams-ai-agent",
            "history": history,
            "provider": self._provider,
            "model": self._model_key,
        }

    # ── generate ─────────────────────────────────────────────────────────
    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        payload = self._build_payload(messages, system)
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{HAMS_MAX_BASE}/v1/chat",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        reply = data.get("reply", "")
        return LLMResponse(
            thought=reply,
            action_type="final_answer",
            final_answer=reply,
            raw=data,
        )

    # ── generate_text ─────────────────────────────────────────────────────
    async def generate_text(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> str:
        response = await self.generate(messages, system=system)
        return response.final_answer or ""

    # ── stream ────────────────────────────────────────────────────────────
    async def stream(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Streaming — hanya support Groq provider."""
        if self._provider != "groq":
            # NVIDIA tidak support streaming, fallback ke generate biasa
            result = await self.generate(messages, system=system)
            yield result.final_answer or ""
            return

        payload = self._build_payload(messages, system)
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{HAMS_MAX_BASE}/v1/chat/stream",
                headers=self._headers(),
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_text():
                    if chunk:
                        yield chunk