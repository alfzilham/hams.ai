"""
Supervisor Agent — orchestrates a team of Worker agents.

Responsibilities:
  1. Decompose the user task into subtasks (via TaskPlanner)
  2. Match each subtask to the best available worker role
  3. Assign subtasks via the MessageBus
  4. Wait for TASK_RESULT / TASK_FAILED messages
  5. Aggregate results into a final response

Worker pool is configured at init time:
    - At least one worker per role you want to use
    - Workers run concurrently; supervisor waits for all to finish

Usage::

    bus = MessageBus()
    supervisor = SupervisorAgent(llm=llm, bus=bus)

    # Register workers
    supervisor.add_worker(WorkerAgent("coder_1", "coder", llm, registry, bus))
    supervisor.add_worker(WorkerAgent("tester_1", "tester", llm, registry, bus))

    result = await supervisor.run("Build a todo REST API with FastAPI")
    print(result.summary)
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from loguru import logger

from agent.multi_agent.message_bus import AgentMessage, MessageBus, MessageType
from agent.multi_agent.worker import WorkerAgent, ROLE_PROMPTS


# ---------------------------------------------------------------------------
# Subtask assignment result
# ---------------------------------------------------------------------------


@dataclass
class SubtaskOutcome:
    subtask_id: str
    title: str
    worker_id: str
    success: bool
    result: str
    error: str | None = None
    steps: int = 0
    tokens: int = 0


@dataclass
class SupervisorResult:
    """Aggregated result from a multi-agent run."""

    task: str
    run_id: str
    success: bool
    summary: str
    subtask_outcomes: list[SubtaskOutcome] = field(default_factory=list)
    total_steps: int = 0
    total_tokens: int = 0
    failed_subtasks: list[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [
            f"## Multi-Agent Result",
            f"**Task:** {self.task}",
            f"**Status:** {'✅ Success' if self.success else '❌ Partial/Failed'}",
            f"**Summary:** {self.summary}",
            "",
            "### Subtask Outcomes",
        ]
        for o in self.subtask_outcomes:
            icon = "✅" if o.success else "❌"
            lines.append(f"{icon} **{o.title}** (worker: `{o.worker_id}`)")
            if o.result:
                lines.append(f"   {o.result[:200]}")
            if o.error:
                lines.append(f"   ⚠️ Error: {o.error}")
        lines.append(f"\n**Total:** {self.total_steps} steps, {self.total_tokens:,} tokens")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Role-to-subtask matcher
# ---------------------------------------------------------------------------

ROLE_KEYWORDS: dict[str, list[str]] = {
    "reviewer": ["review", "check", "audit", "quality", "security", "lint"],
    "tester": ["test", "spec", "pytest", "unittest", "coverage", "verify"],
    "documenter": ["document", "docstring", "readme", "comment", "explain"],
    "devops": ["deploy", "docker", "ci", "pipeline", "kubernetes", "infra"],
    "architect": ["design", "architect", "structure", "plan", "decide"],
    "coder": [],  # fallback
}


def _match_role(description: str) -> str:
    """Heuristic: pick the best worker role for a subtask description."""
    lower = description.lower()
    for role, keywords in ROLE_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return role
    return "coder"  # default


# ---------------------------------------------------------------------------
# Supervisor
# ---------------------------------------------------------------------------


class SupervisorAgent:
    """
    Orchestrates a team of workers to complete a complex task.

    The supervisor:
      - Plans the task into subtasks
      - Assigns each subtask to the most appropriate worker
      - Monitors completion via the MessageBus
      - Aggregates results into a SupervisorResult
    """

    SUPERVISOR_ID = "supervisor"

    def __init__(
        self,
        llm: Any,
        bus: MessageBus,
        timeout_per_subtask: float = 120.0,
        progress_cb: Callable[[dict], Awaitable[None]] | None = None,
    ) -> None:
        self.llm = llm
        self.bus = bus
        self.timeout = timeout_per_subtask
        self._workers: dict[str, WorkerAgent] = {}   # worker_id → WorkerAgent
        self._role_pool: dict[str, list[str]] = {}   # role → [worker_ids]
        self._subscription: Any = None
        self._progress_cb = progress_cb

    # -----------------------------------------------------------------------
    # Worker management
    # -----------------------------------------------------------------------

    def add_worker(self, worker: WorkerAgent) -> None:
        """Register a WorkerAgent with the supervisor."""
        self._workers[worker.worker_id] = worker
        self._role_pool.setdefault(worker.role, []).append(worker.worker_id)
        logger.info(f"[supervisor] Registered {worker}")

    def _pick_worker(self, role: str) -> str | None:
        """Pick an available worker for the given role (round-robin)."""
        pool = self._role_pool.get(role, []) or self._role_pool.get("coder", [])
        if not pool:
            return None
        # Simple round-robin: rotate the list on the role key itself
        worker_id = pool[0]
        self._role_pool[role] = pool[1:] + [pool[0]]
        return worker_id

    # -----------------------------------------------------------------------
    # Main entry point
    # -----------------------------------------------------------------------

    async def run(self, task: str) -> SupervisorResult:
        """
        Decompose the task, dispatch to workers, and aggregate results.
        """
        run_id = str(uuid.uuid4())[:12]
        logger.info(f"[supervisor:{run_id}] Starting task: {task[:80]}")

        # Subscribe to the bus for result messages
        self._subscription = await self.bus.subscribe(self.SUPERVISOR_ID)

        # Start all workers
        for worker in self._workers.values():
            if not worker._running:
                await worker.start()

        # Plan the task
        subtasks = await self._plan(task, run_id)
        logger.info(f"[supervisor:{run_id}] Plan: {len(subtasks)} subtasks")
        if self._progress_cb:
            await self._progress_cb({"type": "plan", "subtasks": subtasks})

        # Assign subtasks to workers
        assignments: dict[str, dict[str, Any]] = {}
        for st in subtasks:
            role = _match_role(st["description"])
            worker_id = self._pick_worker(role)
            if not worker_id:
                logger.warning(f"[supervisor] No worker for role {role!r}, skipping {st['id']}")
                continue

            await self.bus.send(
                sender=self.SUPERVISOR_ID,
                recipient=worker_id,
                msg_type=MessageType.TASK_ASSIGNED,
                payload={
                    "subtask_id": st["id"],
                    "description": st["description"],
                    "role": role,
                },
            )
            assignments[st["id"]] = {
                "title": st["title"],
                "worker_id": worker_id,
                "role": role,
                "done": False,
            }
            if self._progress_cb:
                await self._progress_cb({
                    "type": "subtask_assigned",
                    "subtask_id": st["id"],
                    "title": st["title"],
                    "role": role,
                    "worker_id": worker_id,
                })

        # Collect results
        outcomes = await self._collect_results(assignments)

        # Build summary
        successful = sum(1 for o in outcomes if o.success)
        total_steps = sum(o.steps for o in outcomes)
        total_tokens = sum(o.tokens for o in outcomes)
        failed = [o.subtask_id for o in outcomes if not o.success]

        summary = (
            f"Completed {successful}/{len(outcomes)} subtasks. "
            + (f"Failed: {', '.join(failed)}." if failed else "All subtasks succeeded.")
        )

        result = SupervisorResult(
            task=task,
            run_id=run_id,
            success=len(failed) == 0,
            summary=summary,
            subtask_outcomes=outcomes,
            total_steps=total_steps,
            total_tokens=total_tokens,
            failed_subtasks=failed,
        )

        logger.info(f"[supervisor:{run_id}] Done — {summary}")
        return result

    # -----------------------------------------------------------------------
    # Planning
    # -----------------------------------------------------------------------

    async def _plan(self, task: str, run_id: str) -> list[dict[str, Any]]:
        """Use TaskPlanner to decompose the task into subtasks."""
        try:
            from agent.core.task_planner import TaskPlanner
            planner = TaskPlanner(self.llm)
            plan = await planner.plan(task, run_id=run_id)
            return [
                {"id": s.id, "title": s.title, "description": s.description}
                for s in plan.subtasks
            ]
        except Exception as exc:
            logger.warning(f"[supervisor] Planning failed ({exc}), using single subtask.")
            return [{"id": "step_1", "title": "Complete task", "description": task}]

    # -----------------------------------------------------------------------
    # Result collection
    # -----------------------------------------------------------------------

    async def _collect_results(
        self,
        assignments: dict[str, dict[str, Any]],
    ) -> list[SubtaskOutcome]:
        """Wait for all assigned subtasks to report back."""
        outcomes: list[SubtaskOutcome] = []
        pending = set(assignments.keys())
        deadline = asyncio.get_event_loop().time() + self.timeout * len(assignments)

        while pending and self._subscription:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                logger.warning(f"[supervisor] Timeout waiting for: {pending}")
                for sid in pending:
                    a = assignments[sid]
                    outcomes.append(SubtaskOutcome(
                        subtask_id=sid,
                        title=a["title"],
                        worker_id=a["worker_id"],
                        success=False,
                        result="",
                        error="Timeout waiting for worker response",
                    ))
                break

            msg = await self._subscription.receive(timeout=min(remaining, 10.0))
            if msg is None:
                continue

            if msg.type == MessageType.TASK_RESULT:
                sid = msg.payload.get("subtask_id", "")
                if sid in pending:
                    pending.discard(sid)
                    a = assignments[sid]
                    outcomes.append(SubtaskOutcome(
                        subtask_id=sid,
                        title=a["title"],
                        worker_id=msg.payload.get("worker", a["worker_id"]),
                        success=msg.payload.get("success", False),
                        result=msg.payload.get("result", ""),
                        steps=msg.payload.get("steps", 0),
                        tokens=msg.payload.get("tokens", 0),
                    ))
                    if self._progress_cb:
                        await self._progress_cb({
                            "type": "subtask_result",
                            "subtask_id": sid,
                            "title": a["title"],
                            "worker_id": msg.payload.get("worker", a["worker_id"]),
                            "success": msg.payload.get("success", False),
                            "excerpt": (msg.payload.get("result", "") or "")[:240],
                        })

            elif msg.type == MessageType.TASK_FAILED:
                sid = msg.payload.get("subtask_id", "")
                if sid in pending:
                    pending.discard(sid)
                    a = assignments[sid]
                    outcomes.append(SubtaskOutcome(
                        subtask_id=sid,
                        title=a["title"],
                        worker_id=msg.payload.get("worker", a["worker_id"]),
                        success=False,
                        result="",
                        error=msg.payload.get("error", "Unknown error"),
                    ))
                    if self._progress_cb:
                        await self._progress_cb({
                            "type": "subtask_failed",
                            "subtask_id": sid,
                            "title": a["title"],
                            "worker_id": msg.payload.get("worker", a["worker_id"]),
                            "error": msg.payload.get("error", "Unknown error")[:240],
                        })

        return outcomes

    def __repr__(self) -> str:
        return f"SupervisorAgent(workers={list(self._workers.keys())})"
