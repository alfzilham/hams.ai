"""
Anthropic LLM Provider (Claude 3.5 / 3.7 Sonnet)
"""

from __future__ import annotations

import os
from typing import Any, AsyncIterator

import anthropic
from loguru import logger

from agent.llm.base import BaseLLM, LLMResponse


class AnthropicLLM(BaseLLM):
    """
    Integration with Anthropic's Claude models.
    Supports native tool calling.
    """

    def __init__(
        self,
        model: str = "claude-3-7-sonnet-20250219",
        max_tokens: int = 4096,
        temperature: float = 0.0,
        api_key: str | None = None,
    ) -> None:
        super().__init__(model, max_tokens, temperature)
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable is required")
        
        self.client = anthropic.AsyncAnthropic(api_key=self.api_key)

    def _convert_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert standard JSON Schema tools to Anthropic format."""
        anthropic_tools = []
        for tool in tools:
            anthropic_tool = {
                "name": tool["function"]["name"],
                "description": tool["function"].get("description", ""),
                "input_schema": tool["function"]["parameters"],
            }
            anthropic_tools.append(anthropic_tool)
        return anthropic_tools

    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stop_sequences: list[str] | None = None,
    ) -> LLMResponse:
        
        # Extract system prompt if present
        system_prompt = ""
        claude_messages = []
        
        for msg in messages:
            if msg["role"] == "system":
                system_prompt += msg["content"] + "\n"
            else:
                claude_messages.append(msg)

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": claude_messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        
        if system_prompt:
            kwargs["system"] = system_prompt.strip()

        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        if stop_sequences:
            kwargs["stop_sequences"] = stop_sequences

        logger.debug(f"[AnthropicLLM] Generating with {self.model}")
        
        try:
            response = await self.client.messages.create(**kwargs)
            
            content = ""
            tool_calls = []
            
            for block in response.content:
                if block.type == "text":
                    content += block.text
                elif block.type == "tool_use":
                    tool_calls.append({
                        "id": block.id,
                        "type": "function",
                        "function": {
                            "name": block.name,
                            "arguments": str(block.input).replace("'", '"') # Rough json stringify
                        }
                    })

            return LLMResponse(
                content=content.strip(),
                tool_calls=tool_calls if tool_calls else None,
                raw_response=response.model_dump(),
            )
            
        except Exception as e:
            logger.error(f"[AnthropicLLM] Error: {e}")
            raise

    async def generate_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[str]:
        # Simple non-streaming fallback for now
        resp = await self.generate(messages, tools)
        yield resp.content
