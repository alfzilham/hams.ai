"""
OpenAI provider — GPT-4o and GPT-4o-mini.

Supports:
  - gpt-4o, gpt-4o-mini, gpt-4-turbo
  - Function calling (parallel tool use)
  - Streaming
  - 128k token context window

Requires: OPENAI_API_KEY in environment.
"""

from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator

from loguru import logger

from agent.llm.base import BaseLLM, LLMResponse
from agent.core.state import ActionType, ToolCall


class OpenAILLM(BaseLLM):
    """
    OpenAI GPT-4o via the official `openai` Python SDK.

    Usage::

        llm = OpenAILLM(model="gpt-4o")
        response = await llm.generate(messages=[...], tools=[...], system="...")
    """

    DEFAULT_MODEL = "gpt-4o"

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
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from openai import AsyncOpenAI  # type: ignore[import]
                self._client = AsyncOpenAI(api_key=self._api_key)
            except ImportError as exc:
                raise ImportError(
                    "openai package not installed. Run: pip install openai"
                ) from exc
        return self._client

    # -----------------------------------------------------------------------
    # generate()
    # -----------------------------------------------------------------------

    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        client = self._get_client()

        api_messages = self._inject_system(messages, system)

        request: dict[str, Any] = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=api_messages,
        )
        if tools:
            request["tools"] = self._convert_tools(tools)
            request["tool_choice"] = "auto"

        logger.debug(f"[openai] Calling {self.model} — {len(api_messages)} messages")

        resp = await client.chat.completions.create(**request)
        return self._parse_response(resp)

    # -----------------------------------------------------------------------
    # generate_text()
    # -----------------------------------------------------------------------

    async def generate_text(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> str:
        client = self._get_client()
        api_messages = self._inject_system(messages, system)

        resp = await client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=self.temperature,
            messages=api_messages,
        )
        return resp.choices[0].message.content or ""

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
        api_messages = self._inject_system(messages, system)

        stream = await client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=api_messages,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _parse_response(self, resp: Any) -> LLMResponse:
        msg = resp.choices[0].message
        thought = msg.content or ""
        tool_calls: list[ToolCall] = []
        action_type = ActionType.TOOL_CALL
        final_answer: str | None = None

        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(ToolCall(
                    tool_name=tc.function.name,
                    tool_input=args,
                    tool_use_id=tc.id,
                ))
        else:
            action_type = ActionType.FINAL_ANSWER
            final_answer = thought
            thought = ""

        usage = resp.usage
        return LLMResponse(
            thought=thought,
            action_type=action_type,
            tool_calls=tool_calls,
            final_answer=final_answer,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            raw=resp,
        )

    def _inject_system(
        self,
        messages: list[dict[str, Any]],
        system: str | None,
    ) -> list[dict[str, Any]]:
        """OpenAI accepts system as the first message with role='system'."""
        if not system:
            return messages
        # Don't duplicate if already present
        if messages and messages[0].get("role") == "system":
            return messages
        return [{"role": "system", "content": system}, *messages]

    def _convert_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Convert to OpenAI function-calling format.

        OpenAI format:
            {"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}
        """
        converted = []
        for t in tools:
            converted.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("parameters") or t.get("input_schema", {
                        "type": "object",
                        "properties": {},
                    }),
                },
            })
        return converted
