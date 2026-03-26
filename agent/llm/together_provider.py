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
        system: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """
        Agentic generation with tool call support (via JSON mode prompting).
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Build full prompt with system message and tool schemas
        full_system = system or ""
        if tools:
            # We use JSON mode for tools on Together models for better reliability
            full_system += "\n\nAvailable tools:\n" + json.dumps(tools, indent=2)
            full_system += "\n\nRespond with a JSON object in one of these two formats:\n"
            full_system += '{"action": "tool_call", "tool": "<name>", "input": {<args>}, "thought": "<reasoning>"}\n'
            full_system += '{"action": "final_answer", "answer": "<response>", "thought": "<reasoning>"}\n'

        api_messages = []
        if full_system:
            api_messages.append({"role": "system", "content": full_system})
        
        # Add conversation history
        for msg in messages:
            api_messages.append(msg)

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }

        logger.debug(f"[TogetherLLM] Generating with {self.model}")

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(self.BASE_URL, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        content = data["choices"][0]["message"]["content"] or ""
        
        # Parse JSON response if tools were provided
        if tools:
            try:
                # Find JSON block
                import re
                match = re.search(r"\{.*\}", content, re.DOTALL)
                if match:
                    json_data = json.loads(match.group())
                    thought = json_data.get("thought", "")
                    
                    if json_data.get("action") == "tool_call":
                        return LLMResponse(
                            thought=thought,
                            action_type="tool_call",
                            tool_calls=[{
                                "id": f"call_{os.urandom(4).hex()}",
                                "type": "function",
                                "function": {
                                    "name": json_data["tool"],
                                    "arguments": json.dumps(json_data["input"])
                                }
                            }],
                            raw=data
                        )
                    else:
                        return LLMResponse(
                            thought=thought,
                            action_type="final_answer",
                            final_answer=json_data.get("answer", ""),
                            raw=data
                        )
            except Exception as e:
                logger.warning(f"[TogetherLLM] Failed to parse JSON response: {e}")

        # Fallback to plain text if not tools or parsing failed
        return LLMResponse(
            thought="",
            action_type="final_answer",
            final_answer=content,
            raw=data
        )

    async def generate_text(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> str:
        """Simple text generation."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        api_messages = []
        if system:
            api_messages.append({"role": "system", "content": system})
        api_messages.extend(messages)

        payload = {
            "model": self.model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": self.temperature,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(self.BASE_URL, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"] or ""

    async def stream(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Streaming text generation."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        api_messages = []
        if system:
            api_messages.append({"role": "system", "content": system})
        api_messages.extend(messages)

        payload = {
            "model": self.model,
            "messages": api_messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "stream": True,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream("POST", self.BASE_URL, headers=headers, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip() or line.strip() == "data: [DONE]":
                        continue
                    
                    if line.startswith("data: "):
                        try:
                            data = json.loads(line[6:])
                            delta = data["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                        except Exception:
                            continue
