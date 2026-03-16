"""
Anthropic Claude provider — recommended default for the coding agent.

Supports:
  - claude-sonnet-4-5, claude-opus-4, claude-haiku-4-5
  - Native tool use (function calling)
  - Streaming
  - 200k token context window

Requires: ANTHROPIC_API_KEY in environment.
"""

from __future__ import annotations

import os
from typing import Any, AsyncIterator

from loguru import logger

from agent.llm.base import BaseLLM, LLMResponse
from agent.core.state import ActionType, ToolCall


class AnthropicLLM(BaseLLM):
    """
    Anthropic Claude via the official `anthropic` Python SDK.

    Usage::

        llm = AnthropicLLM(model="claude-sonnet-4-5")
        response = await llm.generate(messages=[...], tools=[...], system="...")
    """

    DEFAULT_MODEL = "claude-sonnet-4-5"

    def __init__(
        self,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        api_key: str | None = None,
    ) -> None:
        super().__init__(
            model=model or self.DEFAULT_MODEL,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._client: Any = None   # lazy-init

    # -----------------------------------------------------------------------
    # Client
    # -----------------------------------------------------------------------

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import anthropic  # type: ignore[import]
                self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
            except ImportError as exc:
                raise ImportError(
                    "anthropic package not installed. Run: pip install anthropic"
                ) from exc
        return self._client

    # -----------------------------------------------------------------------
    # generate() — agentic call with tools
    # -----------------------------------------------------------------------

    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        client = self._get_client()

        # Anthropic uses a separate `system` param, not a system message
        api_messages = self._clean_messages(messages)

        request: dict[str, Any] = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=api_messages,
        )
        if system:
            request["system"] = system
        if tools:
            request["tools"] = self._convert_tools(tools)

        logger.debug(f"[anthropic] Calling {self.model} — {len(api_messages)} messages")

        resp = await client.messages.create(**request)

        return self._parse_response(resp)

    # -----------------------------------------------------------------------
    # generate_text() — no tools, plain text
    # -----------------------------------------------------------------------

    async def generate_text(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> str:
        client = self._get_client()

        request: dict[str, Any] = dict(
            model=self.model,
            max_tokens=max_tokens,
            temperature=self.temperature,
            messages=self._clean_messages(messages),
        )
        if system:
            request["system"] = system

        resp = await client.messages.create(**request)
        return "".join(b.text for b in resp.content if hasattr(b, "text"))

    # -----------------------------------------------------------------------
    # stream()
    # -----------------------------------------------------------------------

    async def stream(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        client = self._get_client()

        request: dict[str, Any] = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=self._clean_messages(messages),
        )
        if system:
            request["system"] = system

        async with client.messages.stream(**request) as stream:
            async for text in stream.text_stream:
                yield text

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _parse_response(self, resp: Any) -> LLMResponse:
        """Convert an Anthropic Message into a unified LLMResponse."""
        thought = ""
        tool_calls: list[ToolCall] = []
        final_answer: str | None = None
        action_type = ActionType.TOOL_CALL

        for block in resp.content:
            if block.type == "text":
                thought += block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    tool_name=block.name,
                    tool_input=block.input,
                    tool_use_id=block.id,
                ))

        # If no tool calls, treat the text as the final answer
        if not tool_calls:
            action_type = ActionType.FINAL_ANSWER
            final_answer = thought
            thought = ""

        return LLMResponse(
            thought=thought,
            action_type=action_type,
            tool_calls=tool_calls,
            final_answer=final_answer,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            raw=resp,
        )

    def _clean_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Strip system-role messages (Anthropic doesn't allow them in the messages array)
        and ensure alternating user/assistant turns.
        """
        return [m for m in messages if m.get("role") != "system"]

    def _convert_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Convert from our internal tool schema to Anthropic's format.

        Our format (OpenAI-compatible):
            {"name": "...", "description": "...", "parameters": {...}}

        Anthropic format:
            {"name": "...", "description": "...", "input_schema": {...}}
        """
        converted = []
        for t in tools:
            converted.append({
                "name": t["name"],
                "description": t.get("description", ""),
                "input_schema": t.get("input_schema") or t.get("parameters", {"type": "object", "properties": {}}),
            })
        return converted
