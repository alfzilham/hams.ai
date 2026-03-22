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

# Shorthand alias → full model ID (untuk backward compatibility)
HAMS_MAX_MODELS: dict[str, str] = {
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

# Model ID yang diketahui sebagai Groq provider
_GROQ_MODEL_IDS: set[str] = {
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "llama-3.1-70b-versatile",
    "llama-3.2-90b-vision-preview",
    "gemma2-9b-it",
    "gemma-7b-it",
    "mixtral-8x7b-32768",
    "compound-beta",
    "compound-beta-mini",
    "whisper-large-v3",
}

# Model ID yang diketahui sebagai NVIDIA provider
_NVIDIA_MODEL_IDS: set[str] = {
    "nvidia/llama-3.3-nemotron-super-49b-v1",
    "nvidia/llama-3.1-nemotron-ultra-253b-v1",
    "nvidia/llama-3.1-nemotron-70b-instruct",
    "nvidia/mistral-nemo-minitron-8b-8k-instruct",
}


def _resolve_model(model: str) -> tuple[str, str]:
    """
    Terima shorthand alias ATAU full model ID.
    Return (model_id, provider) dimana provider = "groq" | "nvidia".

    Contoh:
        "groq"                                    → ("llama-3.3-70b-versatile", "groq")
        "llama-3.3-70b-versatile"                 → ("llama-3.3-70b-versatile", "groq")
        "nvidia/llama-3.3-nemotron-super-49b-v1"  → ("nvidia/llama-3.3-nemotron-super-49b-v1", "nvidia")
        "nemotron"                                → ("nemotron-3-super-120b-a12b", "nvidia")
    """
    # 1. Cek apakah shorthand alias
    if model in HAMS_MAX_MODELS:
        model_id = HAMS_MAX_MODELS[model]
        # Tentukan provider dari model_id hasil resolve
        provider = _detect_provider(model_id, original_key=model)
        return model_id, provider

    # 2. Dianggap full model ID langsung
    provider = _detect_provider(model)
    return model, provider


def _detect_provider(model_id: str, original_key: str = "") -> str:
    """Deteksi provider berdasarkan model ID."""
    # Nvidia prefix
    if model_id.startswith("nvidia/"):
        return "nvidia"

    # Cek known sets
    if model_id in _GROQ_MODEL_IDS:
        return "groq"

    if model_id in _NVIDIA_MODEL_IDS:
        return "nvidia"

    # Alias lama yang bukan "groq"
    if original_key and original_key != "groq":
        # shorthand non-groq (deepseek, qwen, dll) → nvidia
        return "nvidia"

    # Default: groq
    return "groq"


class HamsMaxLLM(BaseLLM):
    """
    LLM provider yang memanggil HAMS-MAX API.

    Menerima shorthand alias ATAU full model ID dari frontend:

        # Shorthand (backward compatible)
        llm = HamsMaxLLM(model="groq")
        llm = HamsMaxLLM(model="deepseek")
        llm = HamsMaxLLM(model="nemotron")

        # Full model ID langsung dari chat UI
        llm = HamsMaxLLM(model="llama-3.3-70b-versatile")
        llm = HamsMaxLLM(model="llama-3.1-8b-instant")
        llm = HamsMaxLLM(model="gemma2-9b-it")
        llm = HamsMaxLLM(model="compound-beta")
        llm = HamsMaxLLM(model="nvidia/llama-3.3-nemotron-super-49b-v1")
        llm = HamsMaxLLM(model="nvidia/llama-3.1-nemotron-ultra-253b-v1")
    """

    def __init__(
        self,
        model: str = "groq",
        max_tokens: int = 2048,
        temperature: float = 0.7,
    ) -> None:
        model_id, provider = _resolve_model(model)

        super().__init__(model=model_id, max_tokens=max_tokens, temperature=temperature)

        self._model_key  = model_id
        self._provider   = provider
        self._api_key    = os.environ.get("HAMS_MAX_API_KEY", "")

        if not self._api_key:
            raise RuntimeError("HAMS_MAX_API_KEY environment variable is not set.")

        logger.info(f"[hams-max] provider={self._provider} model={self._model_key}")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _build_payload(self, messages: list[dict], system: str | None = None) -> dict:
        user_message = ""
        history = []
        for msg in messages:
            if msg["role"] in ("user", "assistant"):
                history.append({"role": msg["role"], "content": msg["content"]})

        if history and history[-1]["role"] == "user":
            user_message = history[-1]["content"]
            history = history[:-1]

        return {
            "message":    user_message,
            "session_id": "hams-ai-agent",
            "history":    history,
            "provider":   self._provider,
            "model":      self._model_key,
        }

    # ── generate ──────────────────────────────────────────────────────────
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

    # ── generate_text ──────────────────────────────────────────────────────
    async def generate_text(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> str:
        response = await self.generate(messages, system=system)
        return response.final_answer or ""

    # ── stream ─────────────────────────────────────────────────────────────
    async def stream(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Streaming — hanya support Groq provider. NVIDIA fallback ke generate biasa."""
        if self._provider != "groq":
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