"""
Error Handler — recovery strategies for every error category.

Implements (from Error Handling & Recovery.md):
  1. RetryConfig + async_retry()     — exponential backoff with full jitter
  2. execute_with_fallbacks()        — ranked fallback chain
  3. SelfCorrector                   — asks the LLM to fix its own output
  4. GracefulDegradation             — partial completion report when stuck
  5. classify_anthropic_error()      — maps SDK exceptions → typed AgentErrors

Usage::

    # Retry an LLM call
    result = await async_retry(llm.generate, messages=..., config=LLM_RETRY)

    # Self-correct bad code
    corrector = SelfCorrector(llm)
    fixed = await corrector.correct(task, bad_code, error)
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from typing import Any, Callable

from loguru import logger

from agent.core.exceptions import (
    AgentError,
    ContentPolicyError,
    ContextLengthError,
    DiskFullError,
    InfiniteLoopError,
    LLMError,
    LLMTimeoutError,
    PermissionToolError,
    RateLimitError,
    SyntaxToolError,
)


# ---------------------------------------------------------------------------
# 1. Retry with exponential backoff + full jitter
# ---------------------------------------------------------------------------


@dataclass
class RetryConfig:
    """
    Configuration for exponential-backoff retry.

    Full jitter: delay = uniform(0, min(max_delay, base * multiplier^attempt))
    This avoids thundering-herd when many agents retry simultaneously.
    """

    max_attempts: int = 5
    base_delay: float = 1.0      # seconds
    max_delay: float = 120.0     # seconds
    multiplier: float = 2.0
    jitter: bool = True
    retryable_on: tuple[type[Exception], ...] = field(
        default_factory=lambda: (AgentError,)
    )

    def compute_delay(self, attempt: int) -> float:
        cap = min(self.max_delay, self.base_delay * (self.multiplier ** attempt))
        return random.uniform(0.0, cap) if self.jitter else cap


# Pre-built configs
LLM_RETRY = RetryConfig(max_attempts=5, base_delay=2.0, max_delay=90.0, jitter=True)
TOOL_RETRY = RetryConfig(max_attempts=3, base_delay=0.5, max_delay=10.0, jitter=True)
FAST_RETRY = RetryConfig(max_attempts=2, base_delay=0.0, max_delay=0.0, jitter=False)


async def async_retry(
    fn: Callable[..., Any],
    *args: Any,
    config: RetryConfig = LLM_RETRY,
    **kwargs: Any,
) -> Any:
    """
    Execute an async callable with exponential-backoff retry.

    Respects RateLimitError.retry_after when present.
    Skips retry for non-recoverable errors (e.g. ContentPolicyError).
    """
    last_exc: Exception | None = None

    for attempt in range(config.max_attempts):
        try:
            return await fn(*args, **kwargs)
        except config.retryable_on as exc:
            last_exc = exc
            if not getattr(exc, "recoverable", True):
                raise

            # Use provider-specified retry-after if available
            if isinstance(exc, RateLimitError):
                delay = exc.retry_after
            else:
                delay = config.compute_delay(attempt)

            logger.warning(
                f"[retry] Attempt {attempt + 1}/{config.max_attempts} failed "
                f"({type(exc).__name__}). Retrying in {delay:.1f}s…"
            )
            await asyncio.sleep(delay)

    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 2. Fallback chain
# ---------------------------------------------------------------------------


async def execute_with_fallbacks(
    strategies: list[tuple[str, Callable[[], Any]]],
) -> tuple[str, Any]:
    """
    Try each strategy in order; return (name, result) of the first success.

    Args:
        strategies: list of (label, async_callable) pairs.

    Raises:
        AgentError: if all strategies fail.
    """
    last_exc: Exception | None = None

    for name, fn in strategies:
        try:
            result = await fn() if asyncio.iscoroutinefunction(fn) else fn()
            if name != strategies[0][0]:
                logger.info(f"[fallback] Succeeded with strategy: '{name}'")
            return name, result
        except AgentError as exc:
            logger.warning(f"[fallback] Strategy '{name}' failed: {exc.message}")
            last_exc = exc
        except Exception as exc:
            logger.warning(f"[fallback] Strategy '{name}' raised: {exc}")
            last_exc = AgentError(str(exc))

    raise last_exc or AgentError("All fallback strategies failed.")


# ---------------------------------------------------------------------------
# 3. Self-correction
# ---------------------------------------------------------------------------


class SelfCorrector:
    """
    Asks the LLM to diagnose and fix its own previous output.

    Used when:
      - Generated code has a SyntaxError
      - A tool call returns a validation error
      - A shell command exits non-zero

    The corrector produces a focused "fix this" prompt, calls the LLM,
    validates the result (Python syntax check), and returns the fixed output.
    """

    SYSTEM = (
        "You are an expert debugger embedded in an AI coding agent. "
        "You will receive the original task, the agent's previous output, "
        "and the exact error it caused. "
        "Produce ONLY the corrected code or action — no explanation, "
        "no markdown fences, no preamble."
    )

    def __init__(self, llm: Any, max_attempts: int = 2) -> None:
        self.llm = llm
        self.max_attempts = max_attempts

    async def correct(
        self,
        original_task: str,
        failed_output: str,
        error: AgentError,
    ) -> str:
        """
        Return a corrected version of `failed_output`.

        Raises:
            AgentError: if correction still fails after max_attempts.
        """
        current_output = failed_output
        current_error = error

        for attempt in range(1, self.max_attempts + 1):
            prompt = self._build_prompt(original_task, current_output, current_error)
            logger.info(f"[self_correct] Attempt {attempt}/{self.max_attempts}")

            try:
                corrected = await self.llm.generate_text(
                    messages=[{"role": "user", "content": prompt}],
                    system=self.SYSTEM,
                    max_tokens=2048,
                )
                corrected = corrected.strip()

                # Validate Python syntax if the output looks like Python
                if self._looks_like_python(corrected):
                    self._check_syntax(corrected)

                logger.info("[self_correct] Correction validated OK.")
                return corrected

            except SyntaxToolError as e:
                logger.warning(f"[self_correct] Correction attempt {attempt} still has syntax error.")
                current_output = corrected  # type: ignore[possibly-undefined]
                current_error = e
            except Exception as exc:
                raise AgentError(f"Self-correction LLM call failed: {exc}") from exc

        raise AgentError(
            f"Self-correction failed after {self.max_attempts} attempts.",
            context={"last_output": current_output},
        )

    # -----------------------------------------------------------------------
    # Private
    # -----------------------------------------------------------------------

    def _build_prompt(self, task: str, output: str, error: AgentError) -> str:
        return (
            f"## Original task\n{task}\n\n"
            f"## Agent's output (caused an error)\n```\n{output}\n```\n\n"
            f"## Error raised\n```\n{error.message}\n```\n\n"
            "Provide the corrected version:"
        )

    def _looks_like_python(self, text: str) -> bool:
        keywords = ("def ", "class ", "import ", "return ", "if ", "for ", "async ")
        return any(kw in text for kw in keywords)

    def _check_syntax(self, code: str) -> None:
        import ast
        try:
            ast.parse(code)
        except SyntaxError as e:
            raise SyntaxToolError(
                "self_correction",
                line=e.lineno or 0,
                detail=e.msg,
                context={"code_snippet": code[:200]},
            ) from e


# ---------------------------------------------------------------------------
# 4. Graceful degradation
# ---------------------------------------------------------------------------


class PartialCompletionReport:
    """Structured report produced when the agent cannot fully complete a task."""

    def __init__(
        self,
        task_id: str,
        original_task: str,
        completed_steps: list[str],
        pending_steps: list[str],
        blocking_error: AgentError,
        artifacts: list[str] | None = None,
    ) -> None:
        self.task_id = task_id
        self.original_task = original_task
        self.completed_steps = completed_steps
        self.pending_steps = pending_steps
        self.blocking_error = blocking_error
        self.artifacts = artifacts or []
        self.recommendations = self._generate_recommendations(blocking_error)

    def to_markdown(self) -> str:
        done = "\n".join(f"  - ✅ {s}" for s in self.completed_steps) or "  *(nothing)*"
        todo = "\n".join(f"  - ⏳ {s}" for s in self.pending_steps) or "  *(nothing)*"
        arts = "\n".join(f"  - 📄 `{a}`" for a in self.artifacts) or "  *(none)*"
        recs = "\n".join(f"  {i+1}. {r}" for i, r in enumerate(self.recommendations))
        err = self.blocking_error.to_dict()

        return (
            f"## ⚠️ Task Partially Completed\n\n"
            f"**Task:** {self.original_task}\n\n"
            f"### Completed\n{done}\n\n"
            f"### Remaining\n{todo}\n\n"
            f"### Blocking Error\n"
            f"```\n{err['error_class']}: {err['message']}\n```\n\n"
            f"### Partial Artifacts\n{arts}\n\n"
            f"### Recommended Next Steps\n{recs}\n"
        )

    @staticmethod
    def _generate_recommendations(error: AgentError) -> list[str]:
        if isinstance(error, RateLimitError):
            return [
                "Wait for the rate limit window to reset, then re-run the task.",
                "Consider upgrading your API tier for higher throughput.",
            ]
        if isinstance(error, ContentPolicyError):
            return [
                "Review the task for content that may trigger safety filters.",
                "Rephrase the task to avoid sensitive terminology.",
            ]
        if isinstance(error, DiskFullError):
            return [
                "Free up workspace disk space (`df -h`, then clean build artifacts).",
                "Re-run after freeing space.",
            ]
        if isinstance(error, PermissionToolError):
            return [
                "Check filesystem ACLs for the target directory.",
                "Re-run with the correct permissions.",
            ]
        if isinstance(error, InfiniteLoopError):
            return [
                "Review the task for ambiguous success criteria.",
                "Increase loop detection threshold if the task legitimately requires repetition.",
            ]
        return [
            "Review the error log for the full stack trace.",
            f"Re-run from the last checkpoint: `agent resume --task-id {error.context.get('task_id', '?')}`",
        ]


# ---------------------------------------------------------------------------
# 5. Anthropic error classifier
# ---------------------------------------------------------------------------


def classify_anthropic_error(exc: Exception) -> LLMError:
    """
    Map an Anthropic SDK exception to the corresponding typed AgentError.

    Usage::

        try:
            response = await client.messages.create(...)
        except Exception as e:
            raise classify_anthropic_error(e) from e
    """
    try:
        import anthropic  # type: ignore[import]
        import httpx  # type: ignore[import]

        if isinstance(exc, anthropic.RateLimitError):
            retry_after = 60.0
            try:
                retry_after = float(
                    exc.response.headers.get("retry-after", 60)  # type: ignore[attr-defined]
                )
            except Exception:
                pass
            return RateLimitError(retry_after=retry_after, context={"raw": str(exc)})

        if isinstance(exc, (anthropic.APITimeoutError,)) or (
            hasattr(httpx, "ReadTimeout") and isinstance(exc, httpx.ReadTimeout)
        ):
            return LLMTimeoutError("LLM request timed out", context={"raw": str(exc)})

        if isinstance(exc, anthropic.BadRequestError):
            body = getattr(exc, "body", {}) or {}
            msg = body.get("error", {}).get("message", "")
            if "context" in msg.lower() or "token" in msg.lower():
                return ContextLengthError(context={"raw": msg})
            if "content" in msg.lower() or "policy" in msg.lower():
                return ContentPolicyError(policy_code="content_filter")

        if isinstance(exc, anthropic.AuthenticationError):
            return LLMError(
                "Authentication failed — check ANTHROPIC_API_KEY",
                recoverable=False,
                context={"raw": str(exc)},
            )

    except ImportError:
        pass

    return LLMError(f"Unclassified LLM error: {exc}", context={"raw": str(exc)})
