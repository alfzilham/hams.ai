"""
LLM Router — selects and falls back between providers automatically.

Supports two modes:
  1. Single provider  — always use one LLM
  2. Fallback chain   — try providers in order; move to next on error

Usage::

    # Single provider
    router = LLMRouter.from_env()

    # Fallback: try Claude first, fall back to GPT-4o, then local Ollama
    router = LLMRouter(
        primary=AnthropicLLM(),
        fallbacks=[OpenAILLM(), OllamaLLM()],
    )

    response = await router.generate(messages=[...], tools=[...])
"""

from __future__ import annotations

import os
from typing import Any, AsyncIterator

from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from agent.llm.base import BaseLLM, LLMResponse


class LLMRouter(BaseLLM):
    """
    Routes LLM requests to the best available provider.

    On failure, automatically retries with exponential back-off,
    then tries the next fallback provider.
    """

    def __init__(
        self,
        primary: BaseLLM,
        fallbacks: list[BaseLLM] | None = None,
        max_retries: int = 3,
    ) -> None:
        # Use primary's settings for repr/logging
        super().__init__(
            model=primary.model,
            max_tokens=primary.max_tokens,
            temperature=primary.temperature,
        )
        self._primary = primary
        self._fallbacks = fallbacks or []
        self._max_retries = max_retries
        self._providers: list[BaseLLM] = [primary, *self._fallbacks]

    # -----------------------------------------------------------------------
    # Factory
    # -----------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> "LLMRouter":
        """
        Build a router from environment variables.
        Automatically enables whichever providers have API keys set.
        """
        from agent.llm.ollama_provider import OllamaLLM

        provider_name = os.environ.get("AGENT_LLM_PROVIDER", "ollama").lower()
        model = os.environ.get("AGENT_MODEL")

        providers: list[BaseLLM] = []

        if provider_name == "ollama":
            providers.append(OllamaLLM(model=model or "deepseek-coder"))

        elif provider_name == "groq" or os.environ.get("GROQ_API_KEY"):
            try:
                from agent.llm.groq_provider import GroqLLM
                providers.append(GroqLLM(model=model or "llama3-70b-8192"))
            except ImportError:
                pass

        elif provider_name == "google" or os.environ.get("GOOGLE_API_KEY"):
            try:
                from agent.llm.google_provider import GoogleLLM
                providers.append(GoogleLLM(model=model or "gemini-1.5-flash"))
            except ImportError:
                pass

        # Ollama selalu jadi fallback terakhir
        if not any(isinstance(p, OllamaLLM) for p in providers):
            providers.append(OllamaLLM(model="deepseek-coder"))

        primary = providers[0]
        fallbacks = providers[1:]
        logger.info(
            f"[router] Primary: {primary} | Fallbacks: {[str(f) for f in fallbacks]}"
        )
        return cls(primary=primary, fallbacks=fallbacks)

    # -----------------------------------------------------------------------
    # BaseLLM interface
    # -----------------------------------------------------------------------

    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        return await self._call_with_fallback(
            "generate", messages=messages, tools=tools, system=system, **kwargs
        )

    async def generate_text(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> str:
        return await self._call_with_fallback(
            "generate_text", messages=messages, system=system, max_tokens=max_tokens, **kwargs
        )

    async def stream(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        # Streaming always uses the primary provider only
        async for chunk in self._primary.stream(messages, system=system, **kwargs):
            yield chunk

    # -----------------------------------------------------------------------
    # Internal: fallback logic
    # -----------------------------------------------------------------------

    async def _call_with_fallback(self, method: str, **kwargs: Any) -> Any:
        last_exc: Exception | None = None

        for provider in self._providers:
            try:
                result = await self._call_with_retry(provider, method, **kwargs)
                return result
            except Exception as exc:
                logger.warning(
                    f"[router] {provider} failed ({exc}). "
                    f"{'Trying next fallback...' if provider != self._providers[-1] else 'No more fallbacks.'}"
                )
                last_exc = exc

        raise RuntimeError(
            f"All {len(self._providers)} LLM provider(s) failed. Last error: {last_exc}"
        ) from last_exc

    async def _call_with_retry(self, provider: BaseLLM, method: str, **kwargs: Any) -> Any:
        """Retry a single provider up to max_retries times with exponential back-off."""
        attempt = 0
        delay = 1.0

        while attempt < self._max_retries:
            try:
                return await getattr(provider, method)(**kwargs)
            except Exception as exc:
                attempt += 1
                if attempt >= self._max_retries:
                    raise
                import asyncio
                logger.debug(f"[router] Retry {attempt}/{self._max_retries} for {provider}: {exc}")
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)
