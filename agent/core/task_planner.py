"""
Task Planner — decomposes a complex user task into ordered subtasks.

Uses the LLM to produce a structured TaskPlan before the reasoning loop starts,
giving the agent a roadmap to follow and backtrack against.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel

from agent.core.state import StepStatus, SubTask, TaskPlan

if TYPE_CHECKING:
    from agent.llm.base import BaseLLM


# ---------------------------------------------------------------------------
# Schema for structured LLM output
# ---------------------------------------------------------------------------


class SubTaskSpec(BaseModel):
    id: str
    title: str
    description: str
    depends_on: list[str] = []


class PlanSpec(BaseModel):
    subtasks: list[SubTaskSpec]
    estimated_steps: int


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


PLANNER_SYSTEM = """You are a software engineering task planner.
Your job is to decompose a user task into clear, ordered subtasks.

Rules:
- Each subtask must be atomic — one clear goal.
- List dependencies explicitly (by subtask id).
- Aim for 3–8 subtasks. Don't over-split simple tasks.
- Respond ONLY with valid JSON matching the schema — no markdown, no explanation.

Schema:
{
  "subtasks": [
    {"id": "step_1", "title": "...", "description": "...", "depends_on": []},
    {"id": "step_2", "title": "...", "description": "...", "depends_on": ["step_1"]}
  ],
  "estimated_steps": 12
}"""


class TaskPlanner:
    """
    Produces a TaskPlan from a free-form task description.

    Example::

        planner = TaskPlanner(llm=claude)
        plan = await planner.plan("Build a REST API for a todo app with FastAPI")
    """

    def __init__(self, llm: "BaseLLM") -> None:
        self.llm = llm

    async def plan(self, task: str, run_id: str | None = None) -> TaskPlan:
        """Call the LLM to decompose `task` into a TaskPlan."""
        rid = run_id or str(uuid.uuid4())[:8]
        logger.info(f"[planner:{rid}] Planning task: {task!r}")

        messages = [
            {
                "role": "user",
                "content": (
                    f"Decompose this coding task into subtasks:\n\n{task}\n\n"
                    "Return only JSON."
                ),
            }
        ]

        try:
            raw = await self.llm.generate_text(
                messages=messages,
                system=PLANNER_SYSTEM,
                max_tokens=1024,
            )
            spec = self._parse(raw)
        except Exception as exc:
            logger.warning(f"[planner:{rid}] LLM planning failed ({exc}), using fallback plan.")
            spec = self._fallback_plan(task)

        subtasks = [
            SubTask(
                id=s.id,
                title=s.title,
                description=s.description,
                depends_on=s.depends_on,
                status=StepStatus.PENDING,
            )
            for s in spec.subtasks
        ]

        plan = TaskPlan(
            task_id=rid,
            original_task=task,
            subtasks=subtasks,
            estimated_steps=spec.estimated_steps,
        )
        logger.info(
            f"[planner:{rid}] Plan ready — {len(subtasks)} subtasks, "
            f"~{spec.estimated_steps} estimated steps."
        )
        return plan

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _parse(self, raw: str) -> PlanSpec:
        """Parse JSON from the LLM response, stripping any markdown fences."""
        import json
        import re

        clean = re.sub(r"```(?:json)?|```", "", raw).strip()
        data: dict[str, Any] = json.loads(clean)
        return PlanSpec(**data)

    def _fallback_plan(self, task: str) -> PlanSpec:
        """Single-step fallback used when LLM planning fails."""
        return PlanSpec(
            subtasks=[
                SubTaskSpec(
                    id="step_1",
                    title="Complete task",
                    description=task,
                    depends_on=[],
                )
            ],
            estimated_steps=10,
        )
