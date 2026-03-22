"""
HAMS-MAX LLM Provider — wraps hams-max-api-production.up.railway.app
Implements BaseLLM interface agar bisa dipakai di LLMRouter.

Fitur agentic:
- ReAct-style tool calling via prompt engineering (XML tags)
- Auto-detect Groq vs NVIDIA provider dari model ID
- Streaming support untuk Groq models
- Backward compatible dengan shorthand alias ("groq", "deepseek", dll)
"""

from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any, AsyncIterator

import httpx
from loguru import logger

from agent.llm.base import BaseLLM, LLMResponse

HAMS_MAX_BASE = "https://hams-max-api-production.up.railway.app"

# Shorthand alias → full model ID
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

# Model yang diketahui sebagai Groq
_GROQ_MODELS: set[str] = {
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "llama-3.1-70b-versatile",
    "gemma2-9b-it",
    "gemma-7b-it",
    "mixtral-8x7b-32768",
    "compound-beta",
    "compound-beta-mini",
}

# ReAct system prompt — disisipkan saat ada tools
_REACT_SYSTEM = """You are an autonomous AI agent. Complete tasks by thinking step-by-step and using tools.

## RESPONSE FORMAT

When you need to use a tool:
<thought>Your reasoning about what to do next</thought>
<action>tool_call</action>
<tool>exact_tool_name</tool>
<args>{{"param": "value"}}</args>

When you have the final answer:
<thought>Your reasoning about the conclusion</thought>
<action>final_answer</action>
<answer>Your complete answer here</answer>

## RULES
- Use EXACT tool names from the Available Tools list
- Args must be valid JSON
- Only call ONE tool per response
- After observing tool results, decide the next action
- When the task is done, use final_answer

## AVAILABLE TOOLS
{tools_text}

{base_system}"""


def _resolve_model(model: str) -> tuple[str, str]:
    """
    Terima shorthand alias ATAU full model ID.
    Return (model_id, provider) dimana provider = "groq" | "nvidia".
    """
    # Cek shorthand alias
    if model in HAMS_MAX_MODELS:
        model_id = HAMS_MAX_MODELS[model]
        provider = "groq" if model == "groq" else "nvidia"
        # Special case: beberapa alias lain adalah groq-compatible
        if model_id in _GROQ_MODELS:
            provider = "groq"
        return model_id, provider

    # Full model ID
    if model.startswith("nvidia/"):
        return model, "nvidia"
    if model in _GROQ_MODELS:
        return model, "groq"

    # Default groq untuk model yang tidak dikenali
    return model, "groq"


def _format_tools_text(tools: list[dict]) -> str:
    """Format tool schemas (Anthropic format) menjadi teks yang mudah dipahami LLM."""
    lines = []
    for t in tools:
        name = t.get("name", "")
        desc = t.get("description", "")
        schema = t.get("input_schema", {})
        props = schema.get("properties", {})
        required = schema.get("required", [])

        params = []
        for pname, pinfo in props.items():
            req_marker = "*" if pname in required else "?"
            ptype = pinfo.get("type", "string")
            pdesc = pinfo.get("description", "")
            params.append(f"  {req_marker} {pname} ({ptype}): {pdesc}")

        lines.append(f"### {name}")
        lines.append(f"Description: {desc}")
        if params:
            lines.append("Parameters (* = required):")
            lines.extend(params)
        lines.append("")

    return "\n".join(lines)


def _parse_react_response(text: str) -> tuple[str, str, str | None, dict | None]:
    """
    Parse ReAct XML response.
    Return (thought, action_type, tool_name, tool_args).
    action_type = "tool_call" | "final_answer"
    """
    thought_m  = re.search(r'<thought>(.*?)</thought>', text, re.DOTALL | re.IGNORECASE)
    action_m   = re.search(r'<action>(.*?)</action>',   text, re.DOTALL | re.IGNORECASE)
    tool_m     = re.search(r'<tool>(.*?)</tool>',       text, re.DOTALL | re.IGNORECASE)
    args_m     = re.search(r'<args>(.*?)</args>',       text, re.DOTALL | re.IGNORECASE)
    answer_m   = re.search(r'<answer>(.*?)</answer>',   text, re.DOTALL | re.IGNORECASE)

    thought     = thought_m.group(1).strip() if thought_m else ""
    action_raw  = action_m.group(1).strip().lower() if action_m else "final_answer"

    if action_raw == "tool_call" and tool_m:
        tool_name = tool_m.group(1).strip()
        tool_args = {}
        if args_m:
            try:
                tool_args = json.loads(args_m.group(1).strip())
            except json.JSONDecodeError:
                # Try to extract JSON from messy text
                json_match = re.search(r'\{.*\}', args_m.group(1), re.DOTALL)
                if json_match:
                    try:
                        tool_args = json.loads(json_match.group())
                    except json.JSONDecodeError:
                        pass
        return thought, "tool_call", tool_name, tool_args

    # Final answer
    if answer_m:
        answer = answer_m.group(1).strip()
    else:
        # Fallback: use the raw text as the answer (no structured format detected)
        answer = text.strip()

    return thought, "final_answer", answer, None


class HamsMaxLLM(BaseLLM):
    """
    LLM provider yang memanggil HAMS-MAX API dengan kemampuan agentic penuh.

    Mendukung ReAct-style tool calling via prompt engineering.
    Menerima shorthand alias ATAU full model ID:

        # Alias (backward compatible)
        HamsMaxLLM(model="groq")
        HamsMaxLLM(model="deepseek")

        # Full model ID dari chat UI
        HamsMaxLLM(model="llama-3.3-70b-versatile")
        HamsMaxLLM(model="gemma2-9b-it")
        HamsMaxLLM(model="nvidia/llama-3.3-nemotron-super-49b-v1")
    """

    def __init__(
        self,
        model: str = "groq",
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> None:
        model_id, provider = _resolve_model(model)
        super().__init__(model=model_id, max_tokens=max_tokens, temperature=temperature)

        self._model_key = model_id
        self._provider  = provider
        self._api_key   = os.environ.get("HAMS_MAX_API_KEY", "")

        if not self._api_key:
            raise RuntimeError("HAMS_MAX_API_KEY environment variable is not set.")

        logger.info(f"[hams-max] provider={self._provider} model={self._model_key}")

    # ── Headers + payload ─────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _build_payload(
        self,
        messages: list[dict],
        system: str | None = None,
    ) -> dict:
        """Build payload untuk HAMS-MAX /v1/chat endpoint."""
        history: list[dict] = []
        user_message = ""

        for msg in messages:
            if msg["role"] in ("user", "assistant"):
                history.append({"role": msg["role"], "content": msg["content"]})

        if history and history[-1]["role"] == "user":
            user_message = history[-1]["content"]
            history = history[:-1]

        # Sisipkan system prompt ke pesan pertama jika ada
        if system and history:
            history[0]["content"] = f"{system}\n\n{history[0]['content']}"
        elif system:
            user_message = f"{system}\n\n{user_message}"

        return {
            "message":    user_message,
            "session_id": f"hams-agent-{uuid.uuid4().hex[:8]}",
            "history":    history,
            "provider":   self._provider,
            "model":      self._model_key,
        }

    async def _call_api(self, payload: dict) -> str:
        """Panggil HAMS-MAX /v1/chat dan return teks reply."""
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(
                f"{HAMS_MAX_BASE}/v1/chat",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        return data.get("reply", "")

    # ── generate — agentic (ReAct) ────────────────────────────────────────

    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """
        Main agentic generation dengan ReAct tool calling.

        Jika tools diberikan, inject ReAct system prompt dan parse
        response untuk tool calls atau final answer.
        """
        # Import here to avoid circular imports
        from agent.core.state import ToolCall, ActionType

        if tools:
            # ── Agentic mode: ReAct prompting ──
            tools_text = _format_tools_text(tools)
            react_system = _REACT_SYSTEM.format(
                tools_text=tools_text,
                base_system=system or "",
            )
            payload = self._build_payload(messages, system=react_system)
            raw_text = await self._call_api(payload)

            thought, action_type, tool_or_answer, tool_args = _parse_react_response(raw_text)

            if action_type == "tool_call" and tool_or_answer:
                tc = ToolCall(
                    tool_name=tool_or_answer,
                    tool_use_id=f"tc_{uuid.uuid4().hex[:8]}",
                    tool_input=tool_args or {},
                )
                logger.debug(f"[hams-max] tool_call → {tool_or_answer}({tool_args})")
                return LLMResponse(
                    thought=thought,
                    action_type=ActionType.TOOL_CALL if hasattr(ActionType, 'TOOL_CALL') else "tool_call",
                    tool_calls=[tc],
                    final_answer=None,
                    raw=raw_text,
                )
            else:
                # Final answer
                answer = tool_or_answer or thought or raw_text
                return LLMResponse(
                    thought=thought,
                    action_type=ActionType.FINAL_ANSWER if hasattr(ActionType, 'FINAL_ANSWER') else "final_answer",
                    tool_calls=[],
                    final_answer=answer,
                    raw=raw_text,
                )

        else:
            # ── Simple mode: tidak ada tools ──
            payload = self._build_payload(messages, system=system)
            reply = await self._call_api(payload)
            return LLMResponse(
                thought=reply,
                action_type="final_answer",
                tool_calls=[],
                final_answer=reply,
                raw=reply,
            )

    # ── generate_text — simple text completion ────────────────────────────

    async def generate_text(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> str:
        payload = self._build_payload(messages, system=system)
        return await self._call_api(payload)

    # ── stream ────────────────────────────────────────────────────────────

    async def stream(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Streaming — Groq support. NVIDIA fallback ke generate."""
        if self._provider != "groq":
            result = await self.generate(messages, system=system)
            yield result.final_answer or ""
            return

        payload = self._build_payload(messages, system=system)
        async with httpx.AsyncClient(timeout=180.0) as client:
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