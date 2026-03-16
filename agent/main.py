"""
CLI entrypoint for the AI Coding Agent.

Usage:
    python -m agent.main "Write a Python function that reverses a linked list"
    agent run "Fix the failing tests in auth.py" --provider anthropic --max-steps 20
    agent run "Add type hints to utils.py" --verbose
"""

from __future__ import annotations

import asyncio
import sys
from typing import Optional

import typer
from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

app = typer.Typer(
    name="agent",
    help="AI Coding Agent — autonomous software engineering assistant",
    add_completion=False,
)
console = Console()


def _setup_logging(verbose: bool) -> None:
    logger.remove()
    level = "DEBUG" if verbose else "INFO"
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
        level=level,
        colorize=True,
    )


def _build_agent(
    provider: str,
    model: str | None,
    max_steps: int,
    verbose: bool,
) -> "Agent":  # type: ignore[name-defined]  # noqa: F821
    """Lazy import and construct the agent with the chosen LLM provider."""
    from agent.core.agent import Agent

    # Import LLM provider
    if provider == "anthropic":
        from agent.llm.anthropic_provider import AnthropicLLM
        llm = AnthropicLLM(model=model or "claude-sonnet-4-5")
    elif provider == "openai":
        from agent.llm.openai_provider import OpenAILLM
        llm = OpenAILLM(model=model or "gpt-4o")
    elif provider == "ollama":
        from agent.llm.ollama_provider import OllamaLLM
        llm = OllamaLLM(model=model or "llama3")
    else:
        console.print(f"[red]Unknown provider: {provider!r}[/red]")
        raise typer.Exit(code=1)

    # Import tool registry
    from agent.tools.registry import ToolRegistry
    registry = ToolRegistry.default()

    return Agent(llm=llm, tool_registry=registry, max_steps=max_steps, verbose=verbose)


@app.command()
def run(
    task: str = typer.Argument(..., help="The coding task to complete"),
    provider: str = typer.Option("anthropic", "--provider", "-p", help="LLM provider: anthropic | openai | ollama"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Model name (uses provider default if omitted)"),
    max_steps: int = typer.Option(30, "--max-steps", "-n", help="Maximum reasoning steps"),
    verbose: bool = typer.Option(True, "--verbose/--quiet", "-v/-q", help="Show step-by-step logs"),
    no_plan: bool = typer.Option(False, "--no-plan", help="Skip task decomposition"),
) -> None:
    """Run the AI Coding Agent on a task."""
    _setup_logging(verbose)

    console.print(Panel(
        Text(task, style="bold white"),
        title="[cyan]AI Coding Agent[/cyan]",
        border_style="cyan",
    ))

    agent = _build_agent(provider, model, max_steps, verbose)
    agent.use_planner = not no_plan

    response = asyncio.run(agent.run(task))

    if response.success:
        console.print(Panel(
            response.final_answer or "(no output)",
            title="[green]✅ Complete[/green]",
            border_style="green",
        ))
    else:
        console.print(Panel(
            response.error or "Unknown error",
            title=f"[red]❌ {response.status.value}[/red]",
            border_style="red",
        ))

    console.print(
        f"\n[dim]Steps: {response.steps_taken}  |  "
        f"Tokens: {response.total_input_tokens + response.total_output_tokens:,}  |  "
        f"Run ID: {response.run_id}[/dim]"
    )

    raise typer.Exit(code=0 if response.success else 1)


@app.command()
def version() -> None:
    """Print the agent version."""
    from agent import __version__
    console.print(f"ai-coding-agent v{__version__}")


# Allow `python -m agent.main "task"` shorthand
if __name__ == "__main__":
    if len(sys.argv) == 2 and not sys.argv[1].startswith("-"):
        # Treat the single argument as a task for the `run` subcommand
        sys.argv.insert(1, "run")
    app()
