# Environment Setup Guide

## Prerequisites

- Python **3.12+** (check with `python --version`)
- Docker Desktop (for sandbox — chapter 04)
- Git

---

## 1. Python Version

### Check existing version
```bash
python --version   # needs 3.12+
```

### Install via pyenv (recommended — works on all platforms)
```bash
# macOS / Linux
brew install pyenv          # or: curl https://pyenv.run | bash
pyenv install 3.12.0
pyenv local 3.12.0          # pins version for this project
```

### Windows
Download the installer from [python.org](https://www.python.org/downloads/) and check **"Add Python to PATH"** during install.

---

## 2. Clone & Virtual Environment

```bash
git clone https://github.com/yourname/ai-coding-agent.git
cd ai-coding-agent

# Create isolated environment
python -m venv .venv

# Activate
source .venv/bin/activate        # macOS / Linux
.venv\Scripts\activate           # Windows PowerShell

# Verify
python --version                 # should show 3.12.x
which python                     # should point inside .venv/
```

---

## 3. Install Dependencies

```bash
# Upgrade pip first
pip install --upgrade pip

# Install the package in editable mode + all dependencies
pip install -e ".[dev]"

# Verify key packages
pip show anthropic pydantic chromadb docker rich
```

---

## 4. Configure API Keys

```bash
# Copy the template
cp .env.example .env

# Edit .env — add your keys
nano .env    # or open in your editor
```

Minimum required — add at least **one** LLM provider key:

```env
# .env
ANTHROPIC_API_KEY=sk-ant-...      # recommended
OPENAI_API_KEY=sk-...             # optional fallback
TAVILY_API_KEY=tvly-...           # for web search tool
```

### Where to get keys
| Provider | URL |
|---|---|
| Anthropic | https://console.anthropic.com/ |
| OpenAI | https://platform.openai.com/api-keys |
| Tavily | https://tavily.com/ |

> **Never commit `.env`** — it is already in `.gitignore`.

---

## 5. Verify Setup

```bash
# Run the config check
python -c "
from agent.config.settings import settings
print('Settings loaded:', settings)
print('Active providers:', settings.active_providers())
"

# Run a quick smoke test
python -m agent.main version

# Run the full test suite
pytest tests/ -m unit -q
```

---

## 6. Using Ollama (Local Models — No API Key)

```bash
# Install Ollama
brew install ollama           # macOS
# or: https://ollama.com/download

# Start the server
ollama serve

# Pull a coding model
ollama pull codestral
ollama pull llama3

# Run agent with Ollama
AGENT_LLM_PROVIDER=ollama AGENT_MODEL=codestral \
  python -m agent.main "Write a binary search in Python"
```

---

## 7. Project Layout After Setup

```
ai-coding-agent/
├── .venv/             ← virtual environment (git-ignored)
├── .env               ← your API keys (git-ignored)
├── agent/             ← source code
├── config/            ← YAML configuration files
├── tests/             ← test suite
└── workspace/         ← agent working directory (created at runtime)
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: anthropic` | Run `pip install -e ".[dev]"` |
| `ANTHROPIC_API_KEY not set` | Check `.env` file and run `source .env` |
| `chromadb` build fails on Windows | Install [Visual C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) |
| Docker not found | Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) |
| `pyenv: command not found` | Add pyenv to PATH — see [pyenv docs](https://github.com/pyenv/pyenv#installation) |
