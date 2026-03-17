"""
Google Gemini provider — cloud inference via Google AI Studio.

Supports models:
  - gemini-1.5-flash  (fast, free tier)
  - gemini-1.5-pro    (more capable)
  - gemini-2.0-flash  (latest)

Requires: GOOGLE_API_KEY in .env
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, AsyncIterator

from loguru import logger

from agent.llm.base import BaseLLM, LLMResponse
from agent.core.state import ActionType, ToolCall


class GoogleLLM(BaseLLM):
    """
    Google Gemini cloud LLM provider.

    Tool calling is implemented via JSON-mode prompting.

    Usage::

        llm = GoogleLLM(model="gemini-1.5-flash")
        response = await llm.generate(messages=[...], tools=[...], system="...")
    """

    DEFAULT_MODEL = "gemini-1.5-flash"
    TOOL_PROMPT_SUFFIX = """

Respond with a JSON object in one of these two formats:

To call a tool:
{"action": "tool_call", "tool": "<tool_name>", "input": {<tool_arguments>}, "thought": "<your reasoning>"}

When the task is complete:
{"action": "final_answer", "answer": "<your final response>", "thought": "<your reasoning>"}

Respond with ONLY the JSON — no markdown, no explanation outside the JSON.
"""

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
        self.api_key = api_key or os.environ.get("GOOGLE_API_KEY", "")
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import google.generativeai as genai  # type: ignore[import]
                genai.configure(api_key=self.api_key)
                self._client = genai.GenerativeModel(
                    model_name=self.model,
                    generation_config={
                        "max_output_tokens": self.max_tokens,
                        "temperature": self.temperature,
                    },
                )
            except ImportError as exc:
                raise ImportError(
                    "google-generativeai package not installed. Run: pip install google-generativeai"
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

        full_system = self._build_system(system, tools)
        prompt = self._build_prompt(messages, full_system)

        logger.debug(f"[google] Calling {self.model} — {len(messages)} messages")

        resp = await client.generate_content_async(prompt)

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
        prompt = self._build_prompt(messages, system)

        resp = await client.generate_content_async(prompt)
        return resp.text or ""

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
        prompt = self._build_prompt(messages, system)

        async for chunk in await client.generate_content_async(prompt, stream=True):
            if chunk.text:
                yield chunk.text

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _build_system(self, system: str | None, tools: list[dict] | None) -> str:
        parts = [system or "You are a helpful AI coding assistant."]
        if tools:
            tool_descs = "\n".join(
                f"- {t['name']}: {t.get('description', '')}"
                for t in tools
            )
            parts.append(f"\n## Available Tools\n{tool_descs}")
        parts.append(self.TOOL_PROMPT_SUFFIX)
        return "\n".join(parts)

    def _build_prompt(
        self,
        messages: list[dict[str, Any]],
        system: str | None,
    ) -> str:
        """Flatten conversation history into a single prompt string for Gemini."""
        parts = []
        if system:
            parts.append(f"[System]\n{system}\n")
        for m in messages:
            role = m.get("role", "user").capitalize()
            content = m.get("content", "")
            if isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            text_parts.append(block["text"])
                        elif block.get("type") == "tool_result":
                            text_parts.append(f"[Tool result] {block.get('content', '')}")
                        elif block.get("type") == "tool_use":
                            text_parts.append(
                                f"[Tool call: {block['name']}] {json.dumps(block.get('input', {}))}"
                            )
                content = "\n".join(text_parts)
            parts.append(f"[{role}]\n{content}")
        return "\n\n".join(parts)

    def _parse_response(self, resp: Any) -> LLMResponse:
        raw_text: str = resp.text or ""
        raw_text = raw_text.strip()

        # Strip markdown code fences
        raw_text = re.sub(r"^```(?:json)?\n?", "", raw_text)
        raw_text = re.sub(r"\n?```$", "", raw_text)

        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            logger.warning("[google] Could not parse JSON response, treating as final answer.")
            return LLMResponse(
                thought=raw_text,
                action_type=ActionType.FINAL_ANSWER,
                final_answer=raw_text,
            )

        action = data.get("action", "final_answer")
        thought = data.get("thought", "")

        if action == "tool_call":
            tc = ToolCall(
                tool_name=data.get("tool", ""),
                tool_input=data.get("input", {}),
            )
            return LLMResponse(
                thought=thought,
                action_type=ActionType.TOOL_CALL,
                tool_calls=[tc],
            )
        else:
            return LLMResponse(
                thought=thought,
                action_type=ActionType.FINAL_ANSWER,
                final_answer=data.get("answer", raw_text),
            )
