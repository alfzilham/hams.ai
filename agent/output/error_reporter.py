"""
Error Reporter — writes structured error events to an append-only JSONL log.

Schema per event:
  event_id   : UUID v4
  task_id    : task this error belongs to
  timestamp  : UTC ISO-8601
  agent_step : turn number when the error occurred
  error      : {error_class, category, message, recoverable, stack_trace}
  context    : free-form metadata from AgentError.context
  recovery   : {strategy, attempt, outcome, notes}

Usage::

    reporter = ErrorReporter(task_id="run_abc123")
    reporter.log(error, step=5, strategy="retry", outcome="success")
    print(reporter.format_user_message(error, step=5))
"""

from __future__ import annotations

import json
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from agent.core.exceptions import AgentError, error_category

RecoveryStrategy = Literal[
    "retry", "fallback", "self_correct",
    "checkpoint_resume", "degradation", "abort",
]
RecoveryOutcome = Literal["success", "failure", "partial"]


class ErrorReporter:
    """
    Append-only JSONL error log for one task run.

    One file per task; safe for concurrent appends (each write is one line).
    """

    def __init__(
        self,
        log_dir: str = ".agent_logs",
        task_id: str = "default",
    ) -> None:
        self.task_id = task_id
        self.log_path = Path(log_dir) / f"{task_id}_errors.jsonl"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        error: AgentError,
        step: int,
        strategy: RecoveryStrategy,
        outcome: RecoveryOutcome,
        attempt: int = 1,
        notes: str = "",
    ) -> dict[str, Any]:
        """
        Write one error event to the JSONL log and return the event dict.
        """
        event: dict[str, Any] = {
            "event_id": str(uuid.uuid4()),
            "task_id": self.task_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent_step": step,
            "error": {
                "error_class": type(error).__name__,
                "category": error_category(error),
                "message": error.message,
                "recoverable": error.recoverable,
                "stack_trace": traceback.format_exc(),
            },
            "context": error.context,
            "recovery": {
                "strategy": strategy,
                "attempt": attempt,
                "outcome": outcome,
                "notes": notes,
            },
        }

        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")

        return event

    def format_user_message(self, error: AgentError, step: int) -> str:
        """
        Produce a concise, non-technical user-facing message.
        Never exposes stack traces or internal paths.
        """
        category = error_category(error)
        prefix = {
            "llm": "🤖 Model issue",
            "tool": "🔧 Tool error",
            "logic": "🔁 Agent logic issue",
            "environment": "🌐 Environment issue",
        }.get(category, "⚠️ Error")

        hint = (
            "The agent will attempt to recover automatically."
            if error.recoverable
            else "Manual intervention may be required."
        )
        return (
            f"{prefix} at step {step}: {error.message}\n"
            f"{hint}\n"
            f"(Full details logged to: {self.log_path})"
        )

    def load_events(self) -> list[dict[str, Any]]:
        """Return all logged events as a list of dicts."""
        if not self.log_path.exists():
            return []
        events = []
        for line in self.log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return events
