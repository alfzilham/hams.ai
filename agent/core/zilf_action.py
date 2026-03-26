"""
Zilf AI Orchestrator

This module implements the core architecture inspired by advanced Action Engines:
- Multi-Agent System (Planner, Executor, Verifier)
- CodeAct Paradigm (Action Engine)
- External Memory / KV-Cache approach
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Callable, Dict, List

from loguru import logger

from agent.llm.base import BaseLLM
from agent.multi_agent.message_bus import MessageBus
from agent.multi_agent.supervisor import SupervisorAgent
from agent.multi_agent.worker import WorkerAgent
from agent.tools.registry import ToolRegistry


class ZilfActionOrchestrator:
    """
    The main Action Engine orchestrator.
    It wraps the Supervisor and Workers into a cohesive Zilf AI experience.
    """

    def __init__(
        self,
        planner_llm: BaseLLM,
        executor_llm: BaseLLM,
        tool_registry: ToolRegistry | None = None,
        max_steps: int = 30,
        progress_cb: Callable[[dict[str, Any]], Any] | None = None,
    ):
        self.planner_llm = planner_llm
        self.executor_llm = executor_llm
        self.tool_registry = tool_registry or ToolRegistry.default()
        self.max_steps = max_steps
        self.progress_cb = progress_cb
        
        # Core Infrastructure
        self.bus = MessageBus()
        
        # The Planner (Supervisor)
        self.supervisor = SupervisorAgent(
            llm=self.planner_llm,
            bus=self.bus,
            progress_cb=self.progress_cb
        )
        
        # The Executors (Workers)
        # We can add multiple workers with different roles. For Zilf, we want a general coder/executor
        # and perhaps a specialized verifier.
        self._setup_agents()

    def _setup_agents(self) -> None:
        """Initialize the multi-agent team."""
        # 1. Executor Agent (Uses CodeAct paradigm)
        executor = WorkerAgent(
            worker_id="zilf_executor_1",
            role="coder",
            llm=self.executor_llm,
            tool_registry=self.tool_registry,
            bus=self.bus,
            max_steps=self.max_steps
        )
        
        # 2. Verifier Agent (Checks output quality)
        verifier = WorkerAgent(
            worker_id="zilf_verifier_1",
            role="reviewer",
            llm=self.planner_llm, # Usually planner LLM is smarter (e.g. Claude 3.7)
            tool_registry=self.tool_registry,
            bus=self.bus,
            max_steps=self.max_steps
        )
        
        self.supervisor.add_worker(executor)
        self.supervisor.add_worker(verifier)
        logger.info("[Zilf] Orchestrator agents initialized: Planner, Executor, Verifier")

    async def run(self, task: str) -> dict[str, Any]:
        """
        Execute a task using the Zilf architecture.
        """
        logger.info(f"[Zilf] Starting Action Engine for task: {task[:50]}...")
        
        try:
            # The Supervisor handles the breakdown and delegation
            result = await self.supervisor.run(task)
            
            return {
                "success": result.success,
                "summary": result.summary,
                "subtasks": [
                    {
                        "title": o.title,
                        "worker": o.worker_id,
                        "success": o.success,
                        "result": o.result,
                        "error": o.error
                    }
                    for o in result.subtask_outcomes
                ],
                "total_steps": result.total_steps,
                "total_tokens": result.total_tokens
            }
            
        except Exception as e:
            logger.error(f"[Zilf] Fatal error during execution: {e}")
            return {
                "success": False,
                "summary": f"System failure: {str(e)}",
                "error": str(e)
            }
        finally:
            # Ensure we clean up worker tasks
            for worker in self.supervisor._workers.values():
                await worker.stop()
