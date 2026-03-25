# @zilf-ai/cli

Official CLI for [zilf.ai](https://zilf.ai) — AI Coding Agent.

## Install

```powershell
npm install -g @zilf-ai/cli
```

## Prerequisites

- **Node.js** 16+ — [nodejs.org](https://nodejs.org)
- **Python** 3.8+ — [python.org](https://python.org)
- **zilf.ai** project folder (the Python agent)

## Setup

After install, tell the CLI where your zilf.ai project lives:

**PowerShell:**
```powershell
$env:ZILF_PATH = "C:\Users\kamu\zilf.ai"
```

**Linux / Mac:**
```bash
export ZILF_PATH="/home/kamu/zilf.ai"
```

To make it permanent, add the line above to your shell profile (`$PROFILE` on PowerShell, `~/.bashrc` or `~/.zshrc` on Linux/Mac).

## Usage

```powershell
# Interactive chat (default)
zilf

# Run a single task
zilf run "buatkan REST API dengan FastAPI untuk CRUD user"

# List available tools
zilf tools

# Check if backend is running
zilf status

# Show Python backend output (debug)
zilf --verbose

# Use custom port
zilf --port 9000
```

## How it works

```
zilf (CLI)
  └── finds Python on your system
  └── auto-installs requirements.txt (first time)
  └── spawns agent/api.py --port 8000
  └── waits for /health to respond
  └── sends your tasks via POST /run/stream
  └── streams response back to terminal
  └── shuts down Python when you exit
```

## Development (local install)

```powershell
# Di dalam folder cli/
npm install
npm link

# Sekarang "zilf" tersedia di terminal
zilf
```

## Publishing

```powershell
npm login
npm publish --access public
```
