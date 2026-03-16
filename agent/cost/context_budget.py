"""
Context Budget — tracks token usage per component and warns before overflow.

Token budget table (based on Context Window Management.md):

  Component            Max Tokens   % of 32k
  ─────────────────────────────────────────────
  System Prompt         1,500        4.7%
  Task Description        800        2.5%
  Conversation History  8,000       25.0%
  Tool Results         10,000       31.3%
  Working Memory        4,000       12.5%
  Response Buffer       4,000       12.5%
  Safety Margin         3,700       11.5%
  ─────────────────────────────────────────────
  Total                32,000      100.0%

Rule of thumb: never exceed 85% utilization — reserve 15% for output + safety.

Usage::

    tracker = ContextBudgetTracker()
    tracker.update(
        system_prompt="You are a coding agent...",
        task="Fix the null pointer",
        history=messages,
        tool_results=["file contents...", "test output..."],
        working_memory="Plan: step 1...",
    )
    print(tracker.report())
    if tracker.utilization_pct > 85:
        # trigger compression
        ...
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Token budget constants
# ---------------------------------------------------------------------------

BUDGET: dict[str, int] = {
    "system_prompt":    1_500,
    "task_description":   800,
    "history":          8_000,
    "tool_results":    10_000,
    "working_memory":   4_000,
    "response_buffer":  4_000,
    "safety_margin":    3_700,
}

TOTAL_BUDGET: int = sum(BUDGET.values())   # 32,000
UTILIZATION_WARN_PCT: float = 85.0        # warn at this threshold


# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------


def count_tokens(text: str, model: str = "cl100k_base") -> int:
    """
    Count tokens in `text`.

    Uses tiktoken when available; falls back to char / 4 estimate.
    """
    try:
        import tiktoken  # type: ignore[import]
        enc = tiktoken.get_encoding(model)
        return len(enc.encode(text))
    except ImportError:
        return max(1, len(text) // 4)


def count_message_tokens(messages: list[dict[str, Any]]) -> int:
    """
    Estimate token count for a list of OpenAI / Anthropic message dicts.

    Adds 4 tokens overhead per message (role + formatting), plus 2 for
    reply priming, matching the tiktoken message-counting formula.
    """
    total = 2  # reply priming
    for msg in messages:
        total += 4  # per-message overhead
        for value in msg.values():
            total += count_tokens(str(value))
    return total


# ---------------------------------------------------------------------------
# ContextBudgetTracker
# ---------------------------------------------------------------------------


@dataclass
class ContextBudgetTracker:
    """
    Tracks token usage per context component.

    Call `update()` before each LLM call to recompute utilization.
    Check `utilization_pct` or `_warnings` to decide whether to compress.
    """

    system_prompt_tokens: int = 0
    task_tokens:          int = 0
    history_tokens:       int = 0
    tool_result_tokens:   int = 0
    working_memory_tokens: int = 0

    _warnings: list[str] = field(default_factory=list, repr=False)

    def update(
        self,
        *,
        system_prompt: str = "",
        task: str = "",
        history: list[dict[str, Any]] | None = None,
        tool_results: list[str] | None = None,
        working_memory: str = "",
    ) -> None:
        """
        Recompute token counts for each component that is provided.
        Components not passed are left unchanged.
        """
        if system_prompt:
            self.system_prompt_tokens = count_tokens(system_prompt)
        if task:
            self.task_tokens = count_tokens(task)
        if history is not None:
            self.history_tokens = count_message_tokens(history)
        if tool_results is not None:
            self.tool_result_tokens = sum(count_tokens(r) for r in tool_results)
        if working_memory:
            self.working_memory_tokens = count_tokens(working_memory)
        self._check_budgets()

    # ── Properties ───────────────────────────────────────────────────────────

    @property
    def total_input_tokens(self) -> int:
        return (
            self.system_prompt_tokens
            + self.task_tokens
            + self.history_tokens
            + self.tool_result_tokens
            + self.working_memory_tokens
        )

    @property
    def available_for_response(self) -> int:
        """Tokens remaining after input, minus safety margin."""
        return max(0, TOTAL_BUDGET - self.total_input_tokens - BUDGET["safety_margin"])

    @property
    def utilization_pct(self) -> float:
        return round(self.total_input_tokens / TOTAL_BUDGET * 100, 1)

    @property
    def should_compress(self) -> bool:
        return self.utilization_pct >= UTILIZATION_WARN_PCT

    @property
    def warnings(self) -> list[str]:
        return list(self._warnings)

    # ── Internals ─────────────────────────────────────────────────────────────

    def _check_budgets(self) -> None:
        self._warnings.clear()
        checks = {
            "history":       (self.history_tokens,       BUDGET["history"]),
            "tool_results":  (self.tool_result_tokens,   BUDGET["tool_results"]),
            "working_memory":(self.working_memory_tokens, BUDGET["working_memory"]),
        }
        for name, (used, cap) in checks.items():
            if used > cap:
                self._warnings.append(
                    f"⚠️  {name} exceeded budget: {used:,} / {cap:,} tokens"
                )
        if self.utilization_pct >= UTILIZATION_WARN_PCT:
            self._warnings.append(
                f"🚨 Total utilization {self.utilization_pct}% — compression required"
            )

    def report(self) -> str:
        lines = [
            "── Context Budget Report ──────────────────────────────",
            f"  System Prompt  : {self.system_prompt_tokens:>7,} / {BUDGET['system_prompt']:,}",
            f"  Task           : {self.task_tokens:>7,} / {BUDGET['task_description']:,}",
            f"  History        : {self.history_tokens:>7,} / {BUDGET['history']:,}",
            f"  Tool Results   : {self.tool_result_tokens:>7,} / {BUDGET['tool_results']:,}",
            f"  Working Memory : {self.working_memory_tokens:>7,} / {BUDGET['working_memory']:,}",
            f"  ────────────────────────────────────────────────────",
            f"  Total Input    : {self.total_input_tokens:>7,} / {TOTAL_BUDGET:,}  ({self.utilization_pct}%)",
            f"  For Response   : {self.available_for_response:>7,}",
        ]
        if self._warnings:
            lines.append("")
            lines.extend(f"  {w}" for w in self._warnings)
        lines.append("────────────────────────────────────────────────────────")
        return "\n".join(lines)
