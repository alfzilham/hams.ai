"""
Reasoning Loop — the heart of the AI Coding Agent.

Implements the Perceive → Reason → Act → Observe → Reflect cycle
based on the ReAct (Reasoning + Acting) framework.

Each call to `run_step()` performs one full iteration:
  1. Perceive  — build context from current AgentState
  2. Reason    — call LLM to get thought + action decision
  3. Act       — execute chosen tools in the sandbox
  4. Observe   — collect tool outputs
  5. Reflect   — update state, check if done
"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING, Protocol

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
# Reasoning Loop
# ---------------------------------------------------------------------------


class ReasoningLoop:
    """
    Drives the agent through its Perceive → Reason → Act → Observe → Reflect cycle.

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
    ) -> None:
        self.llm = llm
        self.tool_registry = tool_registry
        self.max_steps = max_steps
        self.verbose = verbose

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    async def run(self, state: AgentState) -> AgentState:
        """
        Run the full reasoning loop until the task is complete,
        the agent chooses to return a final answer, or max_steps is reached.
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
            # Shouldn't happen, but guard against infinite loops
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
            # 1. PERCEIVE — assemble context
            messages = self._perceive(state)

            # 2. REASON — call LLM
            llm_response = await self.llm.generate(
                messages=messages,
                tools=self.tool_registry.tool_schemas(),
                system=self._system_prompt(state),
            )
            step.thought = llm_response.thought
            step.action_type = llm_response.action_type
            step.tool_calls = llm_response.tool_calls
            step.final_answer = llm_response.final_answer
            step.input_tokens = llm_response.input_tokens
            step.output_tokens = llm_response.output_tokens

            if self.verbose and step.thought:
                logger.debug(f"  💭 Thought: {step.thought[:200]}")

            # 3. ACT + 4. OBSERVE
            if step.action_type == ActionType.FINAL_ANSWER:
                step.tool_results = []
                step.mark_complete(StepStatus.SUCCESS)
                state.add_step(step)
                self._finish(state, step)
                return state

            step.tool_results = await self._act_and_observe(step.tool_calls)

            # 5. REFLECT
            self._reflect(state, step)
            step.mark_complete(StepStatus.SUCCESS)

        except Exception as exc:
            logger.exception(f"  Step {step_num} raised an exception: {exc}")
            step.status = StepStatus.FAILED
            step.reflection = f"Step failed with error: {exc}"
            state.add_step(step)
            state.status = AgentStatus.FAILED
            state.error = str(exc)
            return state

        state.add_step(step)
        return state

    # -----------------------------------------------------------------------
    # Private: Perceive
    # -----------------------------------------------------------------------

    def _perceive(self, state: AgentState) -> list[dict]:
        """
        Build the message list for the next LLM call.

        First message is always the user's task. Subsequent messages
        are the interleaved thought/action/observation history.
        """
        messages: list[dict] = [{"role": "user", "content": state.task}]
        messages.extend(state.context_messages())
        return messages

    # -----------------------------------------------------------------------
    # Private: Act + Observe
    # -----------------------------------------------------------------------

    async def _act_and_observe(self, tool_calls: list[ToolCall]) -> list[ToolResult]:
        """
        Execute all tool calls chosen by the LLM and collect their outputs.

        Tool calls are executed sequentially. Parallel execution is possible
        for independent tools, but sequential is safer for filesystem ops.
        """
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
    # Private: Reflect
    # -----------------------------------------------------------------------

    def _reflect(self, state: AgentState, step: ReasoningStep) -> None:
        """
        Post-observation reflection: examine tool results, detect errors,
        decide whether the task is complete (when no final_answer is returned).
        """
        failed_tools = [r for r in step.tool_results if not r.success]

        if failed_tools:
            names = [r.tool_name for r in failed_tools]
            step.reflection = (
                f"⚠️  {len(failed_tools)} tool(s) failed: {names}. "
                "Will try to recover on the next step."
            )
            if self.verbose:
                logger.warning(f"  {step.reflection}")
        else:
            step.reflection = "All tools executed successfully."

    def _finish(self, state: AgentState, step: ReasoningStep) -> None:
        """Mark the agent state as complete when a final answer is produced."""
        state.final_answer = step.final_answer
        state.status = AgentStatus.COMPLETE
        state.completed_at = step.completed_at
        if self.verbose:
            logger.success(f"  ✔ Task complete. Answer: {str(step.final_answer)[:200]}")

    # -----------------------------------------------------------------------
    # Private: System prompt
    # -----------------------------------------------------------------------

    def _system_prompt(self, state: AgentState) -> str:
        tools_list = "\n".join(
            f"- {name}: {desc}"
            for name, desc in self.tool_registry.tool_descriptions().items()
        )
        plan_section = ""
        if state.plan:
            completed = len(state.plan.completed_subtasks)
            total = len(state.plan.subtasks)
            plan_section = (
                f"\n\n## Current Plan ({completed}/{total} steps done)\n"
                + "\n".join(
                    f"[{'✓' if s.status.value == 'success' else ' '}] {s.id}: {s.title}"
                    for s in state.plan.subtasks
                )
            )

        return f"""You are an expert AI coding agent. Your job is to complete the given software engineering task autonomously.

## Rules
- Think step by step before acting.
- Use tools to gather information before making changes.
- Prefer small, targeted edits over large rewrites.
- Always verify your work by reading files back or running tests.
- When the task is fully complete, use the final_answer action.
- If you are stuck after 3 failed attempts on a subtask, explain why and stop.

## Available Tools
{tools_list}

## Steps remaining: {state.steps_remaining}{plan_section}

Respond using tool calls. When done, set action_type to final_answer."""
