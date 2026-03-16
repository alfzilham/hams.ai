"""
Checkpoint Manager — persists and restores agent state to/from disk.

Enables crash recovery and task resumption without starting from scratch.

Layout on disk:
    .agent_checkpoints/
        {task_id}/
            step_0001_<checksum>.json
            step_0002_<checksum>.json
            latest.json          ← always a copy of the most recent step

Usage::

    manager = CheckpointManager()

    # Save after each step
    cp = AgentCheckpoint.from_state(state)
    manager.save(cp)

    # Restore on restart
    cp = manager.load_latest(task_id)
    if cp:
        state = cp.to_agent_state()
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Checkpoint data class
# ---------------------------------------------------------------------------


@dataclass
class AgentCheckpoint:
    """Snapshot of agent state at a single reasoning step."""

    task_id: str
    step: int
    task: str
    messages: list[dict[str, Any]]
    working_memory: dict[str, Any]
    completed_steps: list[str]
    plan_subtasks: list[dict[str, Any]] = field(default_factory=list)
    last_tool_result: str | None = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def checksum(self) -> str:
        """Short hash of step + message count — used as filename suffix."""
        payload = json.dumps(
            {"step": self.step, "messages_len": len(self.messages)},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:10]

    @classmethod
    def from_state(cls, state: Any) -> "AgentCheckpoint":
        """Build a checkpoint from an AgentState object."""
        return cls(
            task_id=state.run_id,
            step=state.current_step,
            task=state.task,
            messages=state.context_messages(),
            working_memory={},
            completed_steps=[
                s.id for s in (state.plan.subtasks if state.plan else [])
                if s.status.value == "success"
            ],
            plan_subtasks=[
                {"id": s.id, "title": s.title, "status": s.status.value}
                for s in (state.plan.subtasks if state.plan else [])
            ],
            total_input_tokens=state.total_input_tokens,
            total_output_tokens=state.total_output_tokens,
        )


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class CheckpointManager:
    """
    Append-only checkpoint store.

    Each save creates a new timestamped file and updates `latest.json`.
    Old checkpoints are retained for debugging (no auto-pruning by default).
    """

    def __init__(
        self,
        base_dir: str = ".agent_checkpoints",
        max_checkpoints_per_task: int = 100,
    ) -> None:
        self.base = Path(base_dir)
        self.max_per_task = max_checkpoints_per_task

    def _task_dir(self, task_id: str) -> Path:
        d = self.base / task_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save(self, checkpoint: AgentCheckpoint) -> Path:
        """Persist checkpoint to disk and update the `latest.json` pointer."""
        d = self._task_dir(checkpoint.task_id)
        filename = f"step_{checkpoint.step:04d}_{checkpoint.checksum}.json"
        path = d / filename

        data = json.dumps(asdict(checkpoint), indent=2)
        path.write_text(data, encoding="utf-8")
        (d / "latest.json").write_text(data, encoding="utf-8")

        # Prune old files if over limit
        self._prune(d)
        return path

    def load_latest(self, task_id: str) -> AgentCheckpoint | None:
        """Return the most recent checkpoint, or None if none exists."""
        latest = self._task_dir(task_id) / "latest.json"
        if not latest.exists():
            return None
        try:
            data = json.loads(latest.read_text(encoding="utf-8"))
            return AgentCheckpoint(**data)
        except Exception:
            return None

    def load_step(self, task_id: str, step: int) -> AgentCheckpoint | None:
        """Return the checkpoint for a specific step number, or None."""
        d = self._task_dir(task_id)
        for p in d.glob(f"step_{step:04d}_*.json"):
            try:
                return AgentCheckpoint(**json.loads(p.read_text()))
            except Exception:
                continue
        return None

    def list_checkpoints(self, task_id: str) -> list[Path]:
        """Return all checkpoint files sorted oldest → newest."""
        return sorted(
            self._task_dir(task_id).glob("step_*.json"),
            key=lambda p: p.stem,
        )

    def delete_task(self, task_id: str) -> None:
        """Remove all checkpoints for a task."""
        import shutil
        task_dir = self._task_dir(task_id)
        if task_dir.exists():
            shutil.rmtree(task_dir)

    # -----------------------------------------------------------------------
    # Private
    # -----------------------------------------------------------------------

    def _prune(self, task_dir: Path) -> None:
        """Keep only the most recent `max_per_task` checkpoint files."""
        files = sorted(task_dir.glob("step_*.json"), key=lambda p: p.stat().st_mtime)
        excess = len(files) - self.max_per_task
        for old in files[:excess]:
            try:
                old.unlink()
            except OSError:
                pass
