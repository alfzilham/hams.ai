"""
Agent — top-level orchestrator.

The Agent class is the public entry point. It:
  1. Receives a task string from the user
  2. Optionally plans the task using TaskPlanner
  3. Runs the ReasoningLoop until completion
  4. Returns a structured AgentResponse

Usage::

    from agent.core.agent import Agent
    from agent.llm.anthropic_provider import AnthropicLLM
    from agent.tools.registry import ToolRegistry

    agent = Agent(llm=AnthropicLLM(), tool_registry=ToolRegistry.default())
    result = await agent.run("Write a Python script that fetches GitHub trending repos")
    print(result.final_answer)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from loguru import logger

from agent.core.memory import MemoryManager
from agent.core.reasoning_loop import ReasoningLoop
from agent.core.state import AgentState, AgentStatus, TaskPlan
from agent.core.task_planner import TaskPlanner


# ---------------------------------------------------------------------------
# Agent response (returned to the caller)
# ---------------------------------------------------------------------------


class AgentResponse:
    """Structured result returned after a task run completes."""

    def __init__(self, state: AgentState) -> None:
        self.run_id = state.run_id
        self.task = state.task
        self.status = state.status
        self.final_answer = state.final_answer
        self.error = state.error
        self.steps_taken = state.current_step
        self.total_input_tokens = state.total_input_tokens
        self.total_output_tokens = state.total_output_tokens
        self.started_at = state.started_at
        self.completed_at = state.completed_at
        self._state = state  # keep full state for debugging

    @property
    def success(self) -> bool:
        return self.status == AgentStatus.COMPLETE

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    def __repr__(self) -> str:
        return (
            f"AgentResponse(status={self.status.value!r}, "
            f"steps={self.steps_taken}, "
            f"tokens={self.total_input_tokens + self.total_output_tokens})"
        )


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class Agent:
    """
    Autonomous AI coding agent.

    Orchestrates: TaskPlanner → ReasoningLoop → MemoryManager

    Args:
        llm:            LLM provider instance (AnthropicLLM, OpenAILLM, OllamaLLM)
        tool_registry:  Registry of all available tools
        memory:         Optional MemoryManager; created automatically if omitted
        max_steps:      Hard cap on reasoning iterations (default 30)
        use_planner:    Whether to run task decomposition before the loop (default True)
        verbose:        Stream step-by-step logs to stdout (default True)
    """

    def __init__(
        self,
        llm: Any,
        tool_registry: Any,
        memory: MemoryManager | None = None,
        max_steps: int = 30,
        use_planner: bool = True,
        verbose: bool = True,
    ) -> None:
        self.llm = llm
        self.tool_registry = tool_registry
        self.memory = memory or MemoryManager()
        self.max_steps = max_steps
        self.use_planner = use_planner
        self.verbose = verbose

        self._loop = ReasoningLoop(
            llm=llm,
            tool_registry=tool_registry,
            max_steps=max_steps,
            verbose=verbose,
        )
        self._planner = TaskPlanner(llm=llm)

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    async def run(self, task: str, run_id: str | None = None) -> AgentResponse:
        """
        Execute a task end-to-end and return an AgentResponse.

        This is the main entry point. Call it with any coding task:
          - "Write a binary search implementation with tests"
          - "Fix the failing tests in auth.py"
          - "Add type hints to all functions in utils.py"
        """
        rid = run_id or str(uuid.uuid4())[:12]
        logger.info(f"[agent:{rid}] ▶ Task: {task!r}")

        # Build initial state
        state = AgentState(
            run_id=rid,
            task=task,
            max_steps=self.max_steps,
        )

        # Phase 1: Plan
        if self.use_planner:
            try:
                state.status = AgentStatus.PLANNING
                state.plan = await self._planner.plan(task, run_id=rid)
                self._log_plan(state.plan)
            except Exception as exc:
                logger.warning(f"[agent:{rid}] Planning failed ({exc}), proceeding without plan.")
                state.plan = None

        # Phase 2: Reason → Act → Observe → Reflect loop
        state = await self._loop.run(state)

        # Phase 3: Persist to long-term memory
        if state.final_answer:
            self.memory.memorize(
                content=f"Task: {task}\nResult: {state.final_answer}",
                metadata={
                    "run_id": rid,
                    "steps": state.current_step,
                    "status": state.status.value,
                },
            )

        self.memory.clear_session()
        response = AgentResponse(state)
        self._log_summary(response)
        return response

    # -----------------------------------------------------------------------
    # Convenience sync wrapper (for CLI / scripts)
    # -----------------------------------------------------------------------

    def run_sync(self, task: str, run_id: str | None = None) -> AgentResponse:
        """Synchronous wrapper around `run()` for non-async callers."""
        import asyncio

        return asyncio.run(self.run(task, run_id=run_id))

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _log_plan(self, plan: TaskPlan) -> None:
        if not self.verbose:
            return
        logger.info(f"  📋 Plan ({len(plan.subtasks)} subtasks, ~{plan.estimated_steps} steps):")
        for s in plan.subtasks:
            deps = f" [after: {', '.join(s.depends_on)}]" if s.depends_on else ""
            logger.info(f"     • {s.id}: {s.title}{deps}")

    def _log_summary(self, resp: AgentResponse) -> None:
        if not self.verbose:
            return
        icon = "✅" if resp.success else "❌"
        logger.info(
            f"[agent:{resp.run_id}] {icon} Done — "
            f"status={resp.status.value}, "
            f"steps={resp.steps_taken}, "
            f"tokens={resp.total_input_tokens + resp.total_output_tokens}, "
            f"time={resp.duration_seconds:.1f}s"
            if resp.duration_seconds
            else f"[agent:{resp.run_id}] {icon} Done — status={resp.status.value}"
        )
