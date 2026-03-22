"""
HTTP API for the Hams AI.

Endpoints:
  GET  /health            — liveness + readiness probe
  POST /run               — legacy agent run (blocking)
  POST /run/stream        — legacy agent run (SSE)
  GET  /status/{run_id}   — check task status
  GET  /chat-ui           — web chat interface
  POST /chat              — multitask chat (simple, non-agentic)
  POST /agent/run         — agentic run with full tool access (blocking)
  POST /agent/stream      — agentic run with real-time step streaming (SSE)
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

app = FastAPI(
    title="Hams AI",
    description="Autonomous AI agent API",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_tasks: dict[str, dict[str, Any]] = {}
_start_time = time.time()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class RunRequest(BaseModel):
    task: str = Field(..., min_length=1)
    provider: str = Field("ollama")
    model: str | None = None
    max_steps: int = Field(30, ge=1, le=100)


class RunResponse(BaseModel):
    run_id: str
    status: str
    final_answer: str | None = None
    error: str | None = None
    steps_taken: int = 0
    total_tokens: int = 0
    duration_seconds: float | None = None
    started_at: str = ""
    completed_at: str | None = None


class HealthResponse(BaseModel):
    status: str
    version: str
    timestamp: str
    uptime_seconds: float


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str
    history: list[ChatMessage] | None = []
    model: str | None = Field(default="llama-3.3-70b-versatile")


class ChatResponse(BaseModel):
    session_id: str
    response: str
    model_used: str


class AgentRunRequest(BaseModel):
    task: str = Field(..., min_length=1, description="Task untuk dijalankan agent")
    model: str | None = Field(
        default="llama-3.3-70b-versatile",
        description="Model ID — Groq atau NVIDIA"
    )
    max_steps: int = Field(15, ge=1, le=50, description="Max langkah agent")


class AgentStepInfo(BaseModel):
    step: int
    thought: str
    tools_called: list[dict]
    tool_results: list[dict]
    is_final: bool = False


class AgentRunResponse(BaseModel):
    run_id: str
    status: str
    final_answer: str | None = None
    error: str | None = None
    steps: list[AgentStepInfo]
    steps_taken: int
    duration_seconds: float | None = None
    model_used: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MULTITASK_SYSTEM = """Kamu adalah HAMS.AI — asisten AI serba bisa yang powerful dan cerdas.

## KEMAMPUAN UTAMA
1. **Website & UI** — HTML/CSS/JS lengkap, landing page, dashboard, game web, animasi
2. **Kode Program** — Python, JS, SQL, Bash, API, algoritma, lengkap dengan komentar
3. **Konten** — Artikel, blog, copywriting, esai, email profesional
4. **Analisis** — Perbandingan teknologi, strategi, tabel, breakdown konsep kompleks

## ATURAN
- Kode HTML/CSS/JS: tulis LENGKAP dalam satu blok, siap digunakan
- Artikel/konten: gunakan heading (##, ###) yang jelas
- Analisis: gunakan tabel dan poin-poin terstruktur
- Ikuti bahasa pengguna (Indonesia atau Inggris)
- Tulis SEMUA kode — jangan potong dengan "// ... tambahkan sendiri"
- Langsung berikan hasilnya tanpa disclaimer berlebihan"""


def _build_llm(model: str) -> Any:
    """Build HamsMaxLLM jika key tersedia, fallback ke LLMRouter."""
    hams_key = os.environ.get("HAMS_MAX_API_KEY")
    if hams_key:
        from agent.llm.hams_max_provider import HamsMaxLLM
        return HamsMaxLLM(model=model)
    from agent.llm.router import LLMRouter
    return LLMRouter.from_env()


def _build_agent(model: str, max_steps: int, step_callback=None) -> Any:
    """Build Agent dengan HAMS-MAX LLM + full tool registry."""
    from agent.tools.registry import ToolRegistry
    from agent.core.agent import Agent

    llm = _build_llm(model)
    registry = ToolRegistry.default()

    agent = Agent(
        llm=llm,
        tool_registry=registry,
        max_steps=max_steps,
        use_planner=True,
        verbose=False,
    )

    # Inject step_callback ke reasoning loop
    if step_callback:
        agent._loop.step_callback = step_callback

    return agent


def _serialize_step(step: Any) -> AgentStepInfo:
    """Convert ReasoningStep ke serializable dict."""
    tools_called = []
    tool_results = []

    for tc in (step.tool_calls or []):
        tools_called.append({
            "name":  tc.tool_name,
            "args":  tc.tool_input,
        })

    for tr in (step.tool_results or []):
        tool_results.append({
            "tool":    tr.tool_name,
            "output":  tr.output[:500] if tr.output else "",
            "error":   tr.error,
            "success": tr.success,
        })

    is_final = bool(step.final_answer)

    return AgentStepInfo(
        step=step.step_number,
        thought=step.thought or "",
        tools_called=tools_called,
        tool_results=tool_results,
        is_final=is_final,
    )


# ---------------------------------------------------------------------------
# Legacy endpoints (unchanged)
# ---------------------------------------------------------------------------

def _build_legacy_agent(request: RunRequest) -> Any:
    from agent.tools.registry import ToolRegistry
    from agent.llm.router import LLMRouter
    from agent.core.agent import Agent

    registry = ToolRegistry.default()
    try:
        llm = LLMRouter.from_env()
    except RuntimeError:
        from examples.basic_agent import MockLLM
        llm = MockLLM()

    return Agent(llm=llm, tool_registry=registry, max_steps=request.max_steps,
                 use_planner=True, verbose=False)


@app.get("/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version="0.2.0",
        timestamp=datetime.now(timezone.utc).isoformat(),
        uptime_seconds=round(time.time() - _start_time, 1),
    )


@app.post("/run", response_model=RunResponse, tags=["agent-legacy"])
async def run_task(request: RunRequest) -> RunResponse:
    agent = _build_legacy_agent(request)
    t0 = time.perf_counter()
    response = await agent.run(request.task)
    elapsed = time.perf_counter() - t0
    _tasks[response.run_id] = {"status": response.status.value, "completed": True}
    return RunResponse(
        run_id=response.run_id,
        status=response.status.value,
        final_answer=response.final_answer,
        error=response.error,
        steps_taken=response.steps_taken,
        total_tokens=response.total_input_tokens + response.total_output_tokens,
        duration_seconds=round(elapsed, 2),
        started_at=response.started_at.isoformat() if response.started_at else "",
        completed_at=response.completed_at.isoformat() if response.completed_at else None,
    )


@app.post("/run/stream", tags=["agent-legacy"])
async def run_task_stream(request: RunRequest) -> StreamingResponse:
    async def event_stream() -> AsyncIterator[str]:
        agent = _build_legacy_agent(request)
        response = await agent.run(request.task)
        final_event = {
            "type": "complete" if response.success else "error",
            "run_id": response.run_id,
            "final_answer": response.final_answer,
            "error": response.error,
            "steps": response.steps_taken,
        }
        yield f"data: {json.dumps(final_event)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/status/{run_id}", tags=["agent-legacy"])
async def get_status(run_id: str) -> dict[str, Any]:
    if run_id not in _tasks:
        raise HTTPException(status_code=404, detail=f"Run ID '{run_id}' not found.")
    return _tasks[run_id]


# ---------------------------------------------------------------------------
# Chat UI
# ---------------------------------------------------------------------------

@app.get("/chat-ui", tags=["chat"], include_in_schema=False)
async def chat_ui() -> FileResponse:
    html_path = os.path.join(os.path.dirname(__file__), "templates", "chat.html")
    return FileResponse(html_path, media_type="text/html")


# ---------------------------------------------------------------------------
# /chat — simple multitask chat (non-agentic)
# ---------------------------------------------------------------------------

@app.post("/chat", response_model=ChatResponse, tags=["chat"])
async def chat(req: ChatRequest) -> ChatResponse:
    session_id = req.session_id or str(uuid.uuid4())
    model = req.model or "llama-3.3-70b-versatile"

    context = ""
    for msg in (req.history or []):
        prefix = "User" if msg.role == "user" else "Assistant"
        context += f"{prefix}: {msg.content}\n"

    full_prompt = f"{_MULTITASK_SYSTEM}\n\n{context}User: {req.message}\nAssistant:"

    try:
        llm = _build_llm(model)
        reply = await llm.generate_text(
            messages=[{"role": "user", "content": full_prompt}],
            max_tokens=4096,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return ChatResponse(session_id=session_id, response=reply.strip(), model_used=model)


# ---------------------------------------------------------------------------
# /agent/run — agentic AI (blocking, returns all steps)
# ---------------------------------------------------------------------------

@app.post("/agent/run", response_model=AgentRunResponse, tags=["agent"])
async def agent_run(req: AgentRunRequest) -> AgentRunResponse:
    """
    Jalankan agentic task dengan akses penuh ke tools.
    Blocking — menunggu sampai selesai, return semua steps.

    Tools yang tersedia: filesystem, terminal, web_search, code_executor.
    """
    model = req.model or "llama-3.3-70b-versatile"
    t0 = time.perf_counter()

    try:
        agent = _build_agent(model=model, max_steps=req.max_steps)
        response = await agent.run(req.task)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    elapsed = time.perf_counter() - t0
    steps = [_serialize_step(s) for s in (response._state.steps or [])]

    return AgentRunResponse(
        run_id=response.run_id,
        status=response.status.value,
        final_answer=response.final_answer,
        error=response.error,
        steps=steps,
        steps_taken=response.steps_taken,
        duration_seconds=round(elapsed, 2),
        model_used=model,
    )


# ---------------------------------------------------------------------------
# /agent/stream — agentic AI (real-time SSE step streaming)
# ---------------------------------------------------------------------------

@app.post("/agent/stream", tags=["agent"])
async def agent_stream(req: AgentRunRequest) -> StreamingResponse:
    """
    Jalankan agentic task dengan streaming real-time tiap step via SSE.

    SSE event types:
      {"type": "start",       "task": "...", "model": "..."}
      {"type": "planning",    "subtasks": [...]}
      {"type": "step",        "step": N, "thought": "...", "tools": [...]}
      {"type": "tool_result", "step": N, "tool": "...", "output": "..."}
      {"type": "final",       "answer": "...", "steps_taken": N, "duration": N}
      {"type": "error",       "message": "..."}
    """
    model = req.model or "llama-3.3-70b-versatile"

    async def event_stream() -> AsyncIterator[str]:
        queue: asyncio.Queue[dict] = asyncio.Queue()

        # Step callback — dipanggil setelah tiap step oleh ReasoningLoop
        async def on_step(step: Any) -> None:
            tools_info = [
                {"name": tc.tool_name, "args": tc.tool_input}
                for tc in (step.tool_calls or [])
            ]
            results_info = [
                {
                    "tool":    tr.tool_name,
                    "output":  tr.output[:400] if tr.output else "",
                    "success": tr.success,
                }
                for tr in (step.tool_results or [])
            ]

            await queue.put({
                "type":    "step",
                "step":    step.step_number,
                "thought": step.thought or "",
                "tools":   tools_info,
                "results": results_info,
                "is_final": bool(step.final_answer),
            })

        # Start event
        yield f"data: {json.dumps({'type': 'start', 'task': req.task, 'model': model})}\n\n"

        # Run agent in background task
        t0 = time.perf_counter()

        async def run_agent():
            try:
                agent = _build_agent(model=model, max_steps=req.max_steps, step_callback=on_step)
                response = await agent.run(req.task)
                elapsed = round(time.perf_counter() - t0, 2)

                if response.success:
                    await queue.put({
                        "type":        "final",
                        "answer":      response.final_answer or "",
                        "steps_taken": response.steps_taken,
                        "duration":    elapsed,
                    })
                else:
                    await queue.put({
                        "type":    "error",
                        "message": response.error or "Agent failed",
                    })
            except Exception as e:
                await queue.put({"type": "error", "message": str(e)})
            finally:
                await queue.put({"type": "__done__"})  # sentinel

        task = asyncio.create_task(run_agent())

        # Stream events from queue
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=120.0)
            except asyncio.TimeoutError:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Timeout'})}\n\n"
                break

            if event.get("type") == "__done__":
                break

            yield f"data: {json.dumps(event)}\n\n"

            if event.get("type") in ("final", "error"):
                break

        # Make sure background task is cleaned up
        if not task.done():
            task.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="hams.ai API Server")
    parser.add_argument("--port",   type=int, default=int(os.environ.get("AGENT_PORT", 8000)))
    parser.add_argument("--host",   type=str, default=os.environ.get("AGENT_HOST", "127.0.0.1"))
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    uvicorn.run(
        "agent.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="warning",
    )