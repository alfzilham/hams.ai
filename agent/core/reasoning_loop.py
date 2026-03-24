"""
Reasoning Loop — the heart of the Hams AI.

Implements the Perceive → Reason → Act → Observe → Reflect cycle
based on the ReAct (Reasoning + Acting) framework.

Each call to `run_step()` performs one full iteration:
  1. Perceive  — build context from current AgentState
  2. Reason    — call LLM to get thought + action decision
  3. Act       — execute chosen tools in the sandbox
  4. Observe   — collect tool outputs
  5. Reflect   — update state, check if done

Fixes applied:
  B5  — Smart context windowing (keep task + summarize old, trim tool outputs)
  B12 — Dynamic workspace path from env/config
  B16 — Enhanced _reflect() with output quality check
"""

from __future__ import annotations

import os
import time
import uuid
from typing import TYPE_CHECKING, Awaitable, Callable, Protocol

from loguru import logger

from agent.core.state import (
    ActionType,
    AgentState,
    AgentStatus,
    ReasoningStep,
    StepStatus,
    ToolCall,
    ToolResult,
)

if TYPE_CHECKING:
    from agent.llm.base import BaseLLM
    from agent.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Protocol for the LLM response
# ---------------------------------------------------------------------------


class LLMResponse(Protocol):
    """Minimal interface we expect back from any LLM provider."""

    thought: str
    action_type: ActionType
    tool_calls: list[ToolCall]
    final_answer: str | None
    input_tokens: int
    output_tokens: int


# ---------------------------------------------------------------------------
# B5 FIX: Smart Context Windowing Constants
# ---------------------------------------------------------------------------

# Maximum total characters for context (generous but safe)
MAX_CONTEXT_CHARS = 48_000

# Maximum characters per individual tool output
MAX_TOOL_OUTPUT_CHARS = 3_000

# Always keep at least this many recent steps (verbatim)
MIN_RECENT_STEPS = 4

# When trimming, keep first N messages (task context) + last N messages
KEEP_FIRST_MESSAGES = 2
KEEP_LAST_MESSAGES = 10


# ---------------------------------------------------------------------------
# B12 FIX: Dynamic workspace path
# ---------------------------------------------------------------------------

def _get_workspace_path() -> str:
    """
    B12 FIX: Resolve workspace path dynamically.

    Priority:
      1. AGENT_WORKSPACE env var
      2. ./workspace (relative to cwd, for local dev)
      3. /workspace (Docker default)
    """
    # Check env var first
    env_path = os.environ.get("AGENT_WORKSPACE")
    if env_path:
        return env_path

    # Check if running in Docker (common indicator)
    if os.path.exists("/.dockerenv") or os.path.isdir("/workspace"):
        return "/workspace"

    # Local development fallback
    local_workspace = os.path.join(os.getcwd(), "workspace")
    return local_workspace


# ---------------------------------------------------------------------------
# Reasoning Loop
# ---------------------------------------------------------------------------


class ReasoningLoop:
    """
    Drives the agent through its Perceive → Reason → Act → Observe → Reflect cycle.

    Args:
        llm:           LLM provider instance.
        tool_registry: Registry of all available tools.
        max_steps:     Hard cap on iterations.
        verbose:       Log step-by-step to stdout.
        step_callback: Optional async callback called after each step.
                       Signature: async def callback(step: ReasoningStep) -> None
                       Used for real-time streaming of agent progress.

    Usage::

        loop = ReasoningLoop(llm=claude, tool_registry=registry)
        state = await loop.run(state)
    """

    def __init__(
        self,
        llm: "BaseLLM",
        tool_registry: "ToolRegistry",
        max_steps: int = 30,
        verbose: bool = True,
        step_callback: Callable[[ReasoningStep], Awaitable[None]] | None = None,
    ) -> None:
        self.llm = llm
        self.tool_registry = tool_registry
        self.max_steps = max_steps
        self.verbose = verbose
        self.step_callback = step_callback

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    async def run(self, state: AgentState) -> AgentState:
        """
        Run the full reasoning loop until complete, final_answer, or max_steps.
        """
        logger.info(f"[run:{state.run_id}] Starting reasoning loop — task: {state.task!r}")
        state.status = AgentStatus.RUNNING

        while not state.is_done:
            if state.current_step >= self.max_steps:
                logger.warning(f"[run:{state.run_id}] Max steps ({self.max_steps}) reached.")
                state.status = AgentStatus.MAX_STEPS_REACHED
                state.error = f"Stopped after {self.max_steps} steps without completing the task."
                break

            state = await self.run_step(state)

        if state.status == AgentStatus.RUNNING:
            state.status = AgentStatus.FAILED
            state.error = "Loop exited in RUNNING state — unexpected."

        logger.info(f"[run:{state.run_id}] Loop finished — status={state.status}")
        return state

    async def run_step(self, state: AgentState) -> AgentState:
        """Execute one full Perceive → Reason → Act → Observe → Reflect iteration."""
        step_num = state.current_step + 1
        step = ReasoningStep(step_number=step_num, status=StepStatus.RUNNING)

        if self.verbose:
            logger.info(f"  ── Step {step_num}/{self.max_steps} ──")

        try:
            # 1. PERCEIVE
            messages = self._perceive(state)

            # 2. REASON
            llm_response = await self.llm.generate(
                messages=messages,
                tools=self.tool_registry.tool_schemas(),
                system=self._system_prompt(state),
            )
            step.thought      = llm_response.thought
            step.action_type  = llm_response.action_type
            step.tool_calls   = llm_response.tool_calls
            step.final_answer = llm_response.final_answer
            step.input_tokens  = llm_response.input_tokens
            step.output_tokens = llm_response.output_tokens

            if self.verbose and step.thought:
                logger.debug(f"  💭 Thought: {step.thought[:200]}")

            # 3. ACT + 4. OBSERVE
            if step.action_type == ActionType.FINAL_ANSWER:
                step.tool_results = []
                step.mark_complete(StepStatus.SUCCESS)
                state.add_step(step)
                self._finish(state, step)

                # Fire callback for final step
                await self._fire_callback(step)
                return state

            step.tool_results = await self._act_and_observe(step.tool_calls)

            # 5. REFLECT
            self._reflect(state, step)
            step.mark_complete(StepStatus.SUCCESS)

        except Exception as exc:
            logger.exception(f"  Step {step_num} raised an exception: {exc}")
            step.status     = StepStatus.FAILED
            step.reflection = f"Step failed with error: {exc}"
            state.add_step(step)
            state.status = AgentStatus.FAILED
            state.error  = str(exc)

            await self._fire_callback(step)
            return state

        state.add_step(step)

        # ── Fire step callback (for streaming) ──
        await self._fire_callback(step)

        return state

    # -----------------------------------------------------------------------
    # Private: Callback
    # -----------------------------------------------------------------------

    async def _fire_callback(self, step: ReasoningStep) -> None:
        """Invoke step_callback safely — never lets it break the reasoning loop."""
        if self.step_callback is None:
            return
        try:
            await self.step_callback(step)
        except Exception as exc:
            logger.warning(f"[loop] step_callback raised: {exc} — ignoring")

    # -----------------------------------------------------------------------
    # Private: Perceive (B5 FIX — Smart Context Windowing)
    # -----------------------------------------------------------------------

    def _perceive(self, state: AgentState) -> list[dict]:
        """
        Build the message list for the next LLM call.

        B5 FIX: Smart context windowing strategy:
          1. Always keep the original task message (first message)
          2. Truncate individual tool outputs that are too long
          3. If total context still exceeds budget:
             - Keep first N messages (task context + early decisions)
             - Keep last N messages (recent context)
             - Drop middle messages with a [TRIMMED] marker
          4. Much higher budget (48K chars vs old 8K)
        """
        # Start with task message
        messages: list[dict] = [{"role": "user", "content": state.task}]

        # Get all context messages from history
        all_context = state.context_messages()

        # Step 1: Truncate individual tool outputs that are too long
        trimmed_context = self._trim_tool_outputs(all_context)

        # Step 2: Check total size
        total = sum(len(str(m.get("content", ""))) for m in trimmed_context)

        if total <= MAX_CONTEXT_CHARS:
            # Fits within budget — use everything
            messages.extend(trimmed_context)
            return messages

        # Step 3: Smart trimming — keep first + last, drop middle
        messages.extend(
            self._smart_trim(trimmed_context, state)
        )

        return messages

    def _trim_tool_outputs(self, messages: list[dict]) -> list[dict]:
        """
        B5 FIX: Truncate individual tool outputs that are excessively long.

        Tool outputs (file contents, terminal output, etc.) can be huge.
        We truncate each one to MAX_TOOL_OUTPUT_CHARS while preserving
        the beginning and end (most useful parts).
        """
        result = []
        for msg in messages:
            content = msg.get("content", "")

            if isinstance(content, list):
                # Tool result messages have list content
                new_content = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        tool_content = block.get("content", "")
                        if isinstance(tool_content, str) and len(tool_content) > MAX_TOOL_OUTPUT_CHARS:
                            # Keep first half + last half
                            half = MAX_TOOL_OUTPUT_CHARS // 2
                            truncated = (
                                tool_content[:half]
                                + f"\n\n... [TRUNCATED {len(tool_content) - MAX_TOOL_OUTPUT_CHARS} chars] ...\n\n"
                                + tool_content[-half:]
                            )
                            new_content.append({**block, "content": truncated})
                        else:
                            new_content.append(block)
                    else:
                        new_content.append(block)
                result.append({**msg, "content": new_content})

            elif isinstance(content, str) and len(content) > MAX_TOOL_OUTPUT_CHARS:
                half = MAX_TOOL_OUTPUT_CHARS // 2
                truncated = (
                    content[:half]
                    + f"\n\n... [TRUNCATED {len(content) - MAX_TOOL_OUTPUT_CHARS} chars] ...\n\n"
                    + content[-half:]
                )
                result.append({**msg, "content": truncated})
            else:
                result.append(msg)

        return result

    def _smart_trim(self, messages: list[dict], state: AgentState) -> list[dict]:
        """
        B5 FIX: Smart trimming that preserves important context.

        Strategy:
          - Keep first KEEP_FIRST_MESSAGES (early decisions, initial context)
          - Keep last KEEP_LAST_MESSAGES (recent context for continuity)
          - Insert a [CONTEXT TRIMMED] marker in between
          - Include plan summary if available
        """
        total_msgs = len(messages)

        if total_msgs <= KEEP_FIRST_MESSAGES + KEEP_LAST_MESSAGES:
            # Not enough messages to trim meaningfully
            return messages

        first_part = messages[:KEEP_FIRST_MESSAGES]
        last_part = messages[-KEEP_LAST_MESSAGES:]
        dropped_count = total_msgs - KEEP_FIRST_MESSAGES - KEEP_LAST_MESSAGES

        # Build a summary of what was trimmed
        trim_summary_parts = [
            f"[CONTEXT TRIMMED: {dropped_count} messages removed to fit context window]",
        ]

        # Include plan progress if available
        if state.plan:
            completed = len(state.plan.completed_subtasks)
            total = len(state.plan.subtasks)
            trim_summary_parts.append(
                f"Plan progress: {completed}/{total} subtasks completed."
            )

        # Include key facts from trimmed steps
        trimmed_steps = state.steps[
            KEEP_FIRST_MESSAGES // 2 : -(KEEP_LAST_MESSAGES // 2) or None
        ]
        if trimmed_steps:
            key_facts = []
            for step in trimmed_steps[:5]:  # Max 5 key facts
                if step.thought:
                    key_facts.append(f"  Step {step.step_number}: {step.thought[:100]}")
                if step.tool_results:
                    for tr in step.tool_results:
                        status = "✅" if tr.success else "❌"
                        key_facts.append(
                            f"    {status} {tr.tool_name}: {(tr.output or tr.error or '')[:80]}"
                        )
            if key_facts:
                trim_summary_parts.append("Key actions from trimmed context:")
                trim_summary_parts.extend(key_facts)

        trim_marker = {
            "role": "user",
            "content": "\n".join(trim_summary_parts),
        }

        logger.debug(
            f"[loop] Smart trim: {total_msgs} messages → "
            f"keep first {KEEP_FIRST_MESSAGES} + last {KEEP_LAST_MESSAGES}, "
            f"dropped {dropped_count}"
        )

        return first_part + [trim_marker] + last_part

    # -----------------------------------------------------------------------
    # Private: Act + Observe
    # -----------------------------------------------------------------------

    async def _act_and_observe(self, tool_calls: list[ToolCall]) -> list[ToolResult]:
        """Execute all tool calls chosen by the LLM and collect outputs."""
        results: list[ToolResult] = []

        for tc in tool_calls:
            if self.verbose:
                logger.info(f"  🔧 Tool: {tc.tool_name}({list(tc.tool_input.keys())})")

            t0 = time.perf_counter()
            try:
                output = await self.tool_registry.dispatch(tc.tool_name, tc.tool_input)
                elapsed = (time.perf_counter() - t0) * 1000
                result = ToolResult(
                    tool_name=tc.tool_name,
                    tool_use_id=tc.tool_use_id,
                    output=str(output),
                    elapsed_ms=round(elapsed, 2),
                )
                if self.verbose:
                    logger.debug(f"  ✅ {tc.tool_name}: {str(output)[:120]}")

            except Exception as exc:
                elapsed = (time.perf_counter() - t0) * 1000
                result = ToolResult(
                    tool_name=tc.tool_name,
                    tool_use_id=tc.tool_use_id,
                    output="",
                    error=str(exc),
                    elapsed_ms=round(elapsed, 2),
                )
                logger.warning(f"  ❌ {tc.tool_name} failed: {exc}")

            results.append(result)

        return results

    # -----------------------------------------------------------------------
    # Private: Reflect (B16 FIX — Enhanced with quality check)
    # -----------------------------------------------------------------------

    def _reflect(self, state: AgentState, step: ReasoningStep) -> None:
        """
        Post-observation reflection: check errors, analyze output quality,
        and decide if the agent should adjust strategy.

        B16 FIX: Enhanced reflection that checks:
          1. Tool failures (original)
          2. Empty/suspicious outputs
          3. Repeated tool calls (possible loop)
          4. Progress toward task completion
        """
        reflections: list[str] = []

        # 1. Check tool failures
        failed = [r for r in step.tool_results if not r.success]
        if failed:
            names = [r.tool_name for r in failed]
            reflections.append(
                f"⚠️ {len(failed)} tool(s) failed: {names}. "
                "Will try to recover on the next step."
            )

        # 2. Check empty outputs (tool succeeded but returned nothing useful)
        empty_outputs = [
            r for r in step.tool_results
            if r.success and (not r.output or r.output.strip() in ("", "None", "null"))
        ]
        if empty_outputs:
            names = [r.tool_name for r in empty_outputs]
            reflections.append(
                f"⚠️ {len(empty_outputs)} tool(s) returned empty output: {names}. "
                "May need different approach or parameters."
            )

        # 3. Check for repeated tool calls (loop detection)
        if len(state.steps) >= 3:
            recent_tools = []
            for s in state.steps[-3:]:
                for tc in s.tool_calls:
                    recent_tools.append((tc.tool_name, str(tc.tool_input)[:100]))

            # Check if same tool+input called 3+ times
            from collections import Counter
            tool_counts = Counter(recent_tools)
            repeated = [(t, c) for t, c in tool_counts.items() if c >= 3]
            if repeated:
                tool_names = [t[0] for t, _ in repeated]
                reflections.append(
                    f"🔄 Possible loop detected: {tool_names} called 3+ times "
                    "with similar inputs. Consider a different approach."
                )

        # 4. Check progress toward plan (if plan exists)
        if state.plan and not state.plan.is_complete:
            completed = len(state.plan.completed_subtasks)
            total = len(state.plan.subtasks)
            steps_used = state.current_step
            steps_remaining = state.steps_remaining

            if steps_used > 0 and completed == 0 and steps_used >= 5:
                reflections.append(
                    f"⚠️ {steps_used} steps used but 0/{total} subtasks completed. "
                    "Consider simplifying approach or focusing on one subtask."
                )

        # 5. Build final reflection
        if not reflections:
            step.reflection = "All tools executed successfully."
        else:
            step.reflection = " | ".join(reflections)

        if self.verbose and reflections:
            for r in reflections:
                logger.warning(f"  {r}")

    def _finish(self, state: AgentState, step: ReasoningStep) -> None:
        """Mark state as complete when final answer is produced."""
        state.final_answer  = step.final_answer
        state.status        = AgentStatus.COMPLETE
        state.completed_at  = step.completed_at
        if self.verbose:
            logger.success(f"  ✔ Task complete. Answer: {str(step.final_answer)[:200]}")

    # -----------------------------------------------------------------------
    # Private: System prompt (B12 FIX — Dynamic workspace path)
    # -----------------------------------------------------------------------

    def _system_prompt(self, state: AgentState) -> str:
        """
        B12 FIX: Workspace path resolved dynamically from env/config
        instead of hardcoded /workspace.
        """
        workspace = _get_workspace_path()

        tools_list = "\n".join(
            f"- {name}: {desc}"
            for name, desc in self.tool_registry.tool_descriptions().items()
        )
        plan_section = ""
        if state.plan:
            completed = len(state.plan.completed_subtasks)
            total     = len(state.plan.subtasks)
            plan_section = (
                f"\n\n## Current Plan ({completed}/{total} steps done)\n"
                + "\n".join(
                    f"[{'✓' if s.status.value == 'success' else ' '}] {s.id}: {s.title}"
                    for s in state.plan.subtasks
                )
            )

        return f"""You are an expert AI coding agent. Complete the given task autonomously using tools.

## WORKSPACE
- Working directory: {workspace} (persistent storage, gunakan ini)
- Gunakan write_file tool untuk membuat file
- Untuk final answer: tampilkan semua kode lengkap, siap digunakan

## CRITICAL RULES
- NEVER give a final answer before using at least one tool
- NEVER stop after just thinking — you MUST act
- Use tools repeatedly until the task is 100% complete
- Only use final_answer when ALL work is done and verified

## RESPONSE FORMAT — FOLLOW EXACTLY

To call a tool:
<thought>Your reasoning</thought>
<action>tool_call</action>
<tool>exact_tool_name</tool>
<args>{{"param": "value"}}</args>

When fully done:
<thought>Task complete because...</thought>
<action>final_answer</action>
<answer>Your complete answer</answer>

## Available Tools
{tools_list}

## Steps remaining: {state.steps_remaining}{plan_section}"""