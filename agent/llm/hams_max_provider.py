"""
HAMS-MAX Provider — router utama yang memilih mode yang tepat.

Mode:
  - HamsMaxChatLLM     → chat biasa (default)
  - HamsMaxAgentLLM    → agent/ReAct dengan tools
  - HamsMaxThinkingLLM → chat dengan extended thinking

Backward compatible: HamsMaxLLM masih bisa dipakai seperti biasa.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from agent.llm.hams_max_base import HamsMaxBase, resolve_model
from agent.llm.hams_max_chat import HamsMaxChatLLM
from agent.llm.hams_max_agent import HamsMaxAgentLLM
from agent.llm.hams_max_thinking import HamsMaxThinkingLLM
from agent.llm.base import LLMResponse


class HamsMaxLLM(HamsMaxBase):
    """
    Router utama — delegate ke mode yang tepat berdasarkan
    apakah ada tools (agent) atau extended=True (thinking).

    Usage (tidak berubah dari sebelumnya):
        llm = HamsMaxLLM(model="groq", extended=True)
        response = await llm.generate(messages, tools=tools)
    """

    def __init__(
        self,
        model: str = "groq",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        extended: bool = False,
    ) -> None:
        super().__init__(model=model, max_tokens=max_tokens, temperature=temperature)
        self._extended = extended

        # Inisialisasi semua mode dengan model yang sama
        self._chat    = HamsMaxChatLLM(model=model, max_tokens=max_tokens, temperature=temperature)
        self._agent   = HamsMaxAgentLLM(model=model, max_tokens=max_tokens, temperature=temperature)
        self._thinking = HamsMaxThinkingLLM(model=model, max_tokens=max_tokens, temperature=temperature)

    def _pick(self, has_tools: bool) -> HamsMaxBase:
        """Pilih mode yang tepat."""
        if has_tools:
            return self._agent          # Agent: ReAct, tanpa extended thinking
        if self._extended:
            return self._thinking       # Chat + Extended Thinking
        return self._chat               # Chat biasa

    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        extended: bool | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        use_extended = extended if extended is not None else self._extended
        # Override _extended sementara kalau dipassing dari luar
        if extended is not None:
            self._extended = extended
        mode = self._pick(has_tools=bool(tools))
        self._extended = use_extended  # restore
        return await mode.generate(messages, tools=tools, system=system, **kwargs)

    async def generate_text(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        max_tokens: int = 4096,
        extended: bool = False,
        **kwargs: Any,
    ) -> str:
        if extended or self._extended:
            return await self._thinking.generate_text(messages, system=system, max_tokens=max_tokens)
        return await self._chat.generate_text(messages, system=system, max_tokens=max_tokens)

    async def stream(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        mode = self._pick(has_tools=False)
        async for chunk in mode.stream(messages, system=system, **kwargs):
            yield chunk
