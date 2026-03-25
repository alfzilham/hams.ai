"""
Hello World Task — the simplest possible smoke test.

Verifies:
  1. Settings load correctly from .env
  2. ToolRegistry builds with all tools
  3. Filesystem tools work (write + read + delete)
  4. MockLLM + Agent complete a task end-to-end
  5. Pydantic output parser handles tool calls

Run:
    python examples/hello_world_task.py

Expected output: all checks pass with ✓
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def check(label: str, result: bool, detail: str = "") -> None:
    icon = "✓" if result else "✗"
    color = "\033[32m" if result else "\033[31m"
    reset = "\033[0m"
    msg = f"{color}{icon}{reset} {label}"
    if detail:
        msg += f"  [{detail}]"
    print(msg)
    if not result:
        sys.exit(1)


# ---------------------------------------------------------------------------
# 1. Settings
# ---------------------------------------------------------------------------

def test_settings() -> None:
    from agent.config.settings import get_settings
    settings = get_settings()
    check("Settings load", settings is not None)
    check("Agent max_steps > 0", settings.agent.max_steps > 0, str(settings.agent.max_steps))


# ---------------------------------------------------------------------------
# 2. Tool registry
# ---------------------------------------------------------------------------

def test_registry() -> None:
    from agent.tools.registry import ToolRegistry
    registry = ToolRegistry.default()
    names = registry.list_names()
    check("ToolRegistry builds", len(names) > 0)
    check("read_file registered", "read_file" in names)
    check("write_file registered", "write_file" in names)
    check("run_command registered", "run_command" in names)
    check("web_search registered", "web_search" in names)


# ---------------------------------------------------------------------------
# 3. Filesystem tools
# ---------------------------------------------------------------------------

async def test_filesystem() -> None:
    from agent.tools.filesystem import write_file, read_file, delete_file, WORKSPACE_ROOT

    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    test_path = str(WORKSPACE_ROOT / ".smoke_test.txt")

    write_result = await write_file(test_path, "hello smoke test\n")
    check("write_file succeeds", "OK" in write_result, write_result[:60])

    read_result = await read_file(test_path)
    check("read_file returns content", "hello smoke test" in read_result)

    del_result = await delete_file(test_path)
    check("delete_file succeeds", "OK" in del_result, del_result[:60])


# ---------------------------------------------------------------------------
# 4. Pydantic output parser
# ---------------------------------------------------------------------------

def test_parser() -> None:
    from agent.output.parser import LLMOutputParser, FileReadTool

    parser = LLMOutputParser()

    # Clean JSON
    raw = '{"tool": "read_file", "file_path": "/workspace/main.py"}'
    tool = parser.parse_tool_call(raw)
    check("Parser: clean JSON", isinstance(tool, FileReadTool))

    # JSON wrapped in markdown
    raw_md = '```json\n{"tool": "read_file", "file_path": "/workspace/main.py"}\n```'
    tool_md = parser.parse_tool_call(raw_md)
    check("Parser: markdown-wrapped JSON", isinstance(tool_md, FileReadTool))

    # JSON embedded in prose
    raw_prose = 'I will read the file.\n{"tool": "read_file", "file_path": "/workspace/main.py"}\nLet me know.'
    tool_prose = parser.parse_tool_call(raw_prose)
    check("Parser: JSON in prose", isinstance(tool_prose, FileReadTool))

    # Safe path validation
    try:
        from agent.output.parser import FileWriteTool
        FileWriteTool(tool="write_file", file_path="../../../etc/passwd", content="evil")
        check("SafeFilePath blocks traversal", False)
    except Exception:
        check("SafeFilePath blocks traversal", True)


# ---------------------------------------------------------------------------
# 5. Pydantic schemas
# ---------------------------------------------------------------------------

def test_schemas() -> None:
    from agent.output.schemas import TaskPlan, TaskStep

    plan = TaskPlan(
        task_id="t1",
        original_task="Build an API",
        steps=[
            TaskStep(step_id=1, title="Setup", description="Create project structure", dependencies=[]),
            TaskStep(step_id=2, title="Implement", description="Write code", dependencies=[1]),
            TaskStep(step_id=3, title="Test", description="Run tests", dependencies=[2]),
        ],
    )

    # Initially only step 1 is ready
    ready = plan.get_next_steps([])
    check("Plan: step 1 ready when no deps done", len(ready) == 1 and ready[0].step_id == 1)

    # After step 1 done, step 2 unlocks
    plan.mark_done(1)
    ready2 = plan.get_next_steps([1])
    check("Plan: step 2 unlocks after step 1", any(s.step_id == 2 for s in ready2))

    check("Plan: not complete yet", not plan.is_complete)

    plan.mark_done(2)
    plan.mark_done(3)
    check("Plan: complete when all done", plan.is_complete)


# ---------------------------------------------------------------------------
# 6. End-to-end mock agent run
# ---------------------------------------------------------------------------

async def test_agent_e2e() -> None:
    from examples.basic_agent import MockLLM
    from agent.core.agent import Agent
    from agent.tools.registry import ToolRegistry

    registry = ToolRegistry.default()
    llm = MockLLM()
    agent = Agent(llm=llm, tool_registry=registry, use_planner=False, verbose=False)

    response = await agent.run("Demo task: create hello.py and run it")
    check("Agent e2e: completes without exception", True)
    check("Agent e2e: has a run_id", bool(response.run_id))


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def main() -> None:
    print("\n🔍 Zilf AI — Smoke Tests\n")

    print("── Settings ──")
    test_settings()

    print("\n── Tool Registry ──")
    test_registry()

    print("\n── Filesystem Tools ──")
    await test_filesystem()

    print("\n── Output Parser ──")
    test_parser()

    print("\n── Pydantic Schemas ──")
    test_schemas()

    print("\n── End-to-End (MockLLM) ──")
    await test_agent_e2e()

    print("\n\033[32m✓ All checks passed!\033[0m\n")


if __name__ == "__main__":
    asyncio.run(main())
