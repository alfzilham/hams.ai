# Hams AI 🤖

An open-source autonomous coding assistant that can write, test, debug, and deploy code — powered by Claude, GPT-4o, or local models via Ollama.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

---

## What It Does

The agent receives a natural language task and autonomously:

1. **Plans** — breaks the task into ordered subtasks
2. **Acts** — uses tools: filesystem, terminal, web search, code executor
3. **Observes** — reads output, detects errors
4. **Reflects** — updates memory, decides the next step
5. **Repeats** — until the task is complete or max steps reached

---

## Core Capabilities

| Capability | Description |
|---|---|
| Code generation | Writes new code from specs or examples |
| Bug fixing | Detects and patches failing tests or runtime errors |
| Test creation | Generates pytest suites with mocks and fixtures |
| Documentation | Writes docstrings, READMEs, and API references |
| Environment setup | Installs dependencies, configures .env files |
| Self-improvement | Reflects on past runs and refines its approach |

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/yourname/hams-ai.git
cd hams-ai

# 2. Set up Python environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 3. Configure API keys
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

# 4. Run your first task
python -m agent.main "Write a Python function that reverses a linked list, with tests"
```

---

## Architecture

```
User Task
   │
   ▼
Agent Core ──────────────────────────────────────┐
   │                                              │
   ├── LLM Brain (Claude / GPT-4o / Ollama)      │
   │      └── Reasoning Engine                   │
   │             └── ReAct Loop                  │
   │                  Think → Act → Observe      │
   │                       └── Reflection ───────┘
   │                                (memory update)
   ├── Memory System
   │      ├── Short-term  (context window)
   │      └── Long-term   (ChromaDB / FAISS)
   │
   ├── Tool Suite
   │      ├── Filesystem   read/write/search files
   │      ├── Terminal     shell commands in Docker sandbox
   │      ├── Web Search   Tavily / SerpAPI
   │      └── Code Exec    isolated Python/JS/Bash runner
   │
   └── Planning Module
          ├── Task Decomposition
          └── Step Sequencing
```

---

## Project Structure

```
hams-ai/
├── agent/
│   ├── core/          # Agent, reasoning loop, planner, state
│   ├── llm/           # LLM provider abstraction (Claude, OpenAI, Ollama)
│   ├── tools/         # All agent tools
│   ├── memory/        # Context manager, episodic, vector store
│   ├── prompts/       # System prompts and ReAct templates
│   ├── sandbox/       # Docker manager and isolation
│   ├── multi_agent/   # Supervisor + worker orchestration
│   └── output/        # Pydantic schemas and output parser
├── config/            # YAML configs for agent, sandbox, logging
├── docker/            # Dockerfiles and sandbox entrypoint
├── tests/             # Unit, integration, benchmarks
├── observability/     # Tracing, cost tracking, dashboard
├── security/          # Prompt injection, audit log
└── docs/              # Architecture, API reference, contributing
```

---

## Supported LLM Providers

| Provider | Models | Notes |
|---|---|---|
| Anthropic | claude-sonnet-4, claude-opus-4 | Recommended — best tool use |
| OpenAI | gpt-4o, gpt-4o-mini | Full function calling support |
| Ollama | llama3, codestral, qwen2.5-coder | Local, no API key needed |

---

## Contributing

See [docs/contributing.md](docs/contributing.md) for the PR process, code style guide, and testing requirements.

---

## License

MIT — see [LICENSE](LICENSE).
