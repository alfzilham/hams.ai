# 🤖 Zilf AI

<div align="center">

![Zilf AI Banner](https://img.shields.io/badge/Zilf%20AI-Autonomous%20Coding%20Assistant-blue?style=for-the-badge&logo=robot)

[![Build Status](https://img.shields.io/github/actions/workflow/status/alfizilham/zilf-ai/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/alfizilham/zilf-ai/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.14+-blue.svg?style=flat-square&logo=python)](https://www.python.org/)
[![Version](https://img.shields.io/badge/version-0.1.0-orange.svg?style=flat-square)](pyproject.toml)
[![npm](https://img.shields.io/npm/v/@zilf-ai/cli?style=flat-square&logo=npm&label=%40zilf-ai%2Fcli)](https://www.npmjs.com/package/@zilf-ai/cli)
[![Open Source](https://img.shields.io/badge/Open%20Source-❤️-red.svg?style=flat-square)](https://github.com/alfizilham/zilf-ai)

**AI Coding Agent open source yang berjalan lokal — tanpa biaya API, tanpa batas.**

[Demo](#-demo) · [Instalasi](#-instalasi) · [CLI (npm)](#-cli-via-npm) · [Penggunaan](#-penggunaan) · [Kontribusi](#-kontribusi) · [Roadmap](#-roadmap)

</div>

---

## ✨ Apa itu Zilf AI?

Zilf AI adalah **autonomous coding assistant** yang dapat menulis, menjalankan, memperbaiki, dan memverifikasi kode secara mandiri. Dibangun di atas arsitektur **ReAct (Reasoning + Acting)**, agent ini berpikir langkah demi langkah sebelum mengambil tindakan — persis seperti developer sungguhan.

### Keunggulan Zilf AI
- 🆓 **100% Gratis** — Jalankan lokal dengan Ollama, tidak perlu bayar API
- 🔒 **Privat** — Kode kamu tidak dikirim ke server manapun (mode Ollama)
- 🔌 **Multi-Provider** — Dukung Ollama, Groq, dan Google Gemini
- 🛠️ **8 Tools Bawaan** — File system, terminal, web search, code executor
- 🐳 **Sandbox Docker** — Eksekusi kode dalam environment yang terisolasi
- 🔍 **Observability** — Tracing, cost tracking, dan dashboard built-in
- 💻 **CLI Global** — Install sekali via npm, jalankan `zilf` dari mana saja

---

## 🎬 Demo

```
╭─────────────────────────── Zilf AI ───────────────────────────╮
│ Create a Python file called hello.py that prints               │
│ 'Hello from Zilf AI!' and verify it runs correctly.           │
╰────────────────────────────────────────────────────────────────╯

💭 Thought: I need to create hello.py and verify it works...
🔧 Tool: write_file(path=/workspace/hello.py)
🔧 Tool: run_command(command=python hello.py)

╭────────────────────── ✅ Complete ─────────────────────────────╮
│ File hello.py created and verified successfully.               │
│ Output: Hello from Zilf AI!                                    │
╰────────────────────────────────────────────────────────────────╯

Steps: 2  |  Tokens: 0  |  Time: 45.7s
```

---

## 📦 Instalasi

### Prasyarat
- Python 3.14+
- [Ollama](https://ollama.com/download) (untuk model lokal)
- Docker Desktop (opsional, untuk sandbox)
- Git

### 1. Clone Repository

```bash
git clone https://github.com/alfizilham/zilf-ai.git
cd zilf-ai
```

### 2. Buat Virtual Environment

```bash
python -m venv .venv

# Windows PowerShell
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Setup Ollama (Gratis, Lokal)

```bash
# Download Ollama dari https://ollama.com/download
# Lalu pull model yang diinginkan:
ollama pull deepseek-coder   # Recommended untuk coding (776 MB)
ollama pull llama3           # General purpose (4.7 GB)
ollama pull codellama        # Spesialis coding (3.8 GB)
ollama pull mistral          # Cepat dan ringan (4.4 GB)
```

### 5. Setup API Keys (Opsional)

```bash
cp .env.example .env
# Edit .env dan isi API key yang kamu punya
```

```env
# Ollama (tidak perlu key — jalankan lokal)
OLLAMA_BASE_URL=http://localhost:11434

# Groq (gratis, tier: 1000 req/hari)
GROQ_API_KEY=gsk_...

# Google Gemini (gratis, tier: 1500 req/hari)
GOOGLE_API_KEY=AIzaSy...

# Tavily Web Search (gratis, 1000 req/bulan)
TAVILY_API_KEY=tvly-...
```

---

## 💻 CLI via npm

Gunakan Zilf AI langsung dari terminal mana saja menggunakan `zilf` — tanpa perlu masuk ke folder project setiap kali.

### Prasyarat CLI
- [Node.js](https://nodejs.org) 16+
- Python 3.14+ (sudah terinstall dari langkah di atas)
- Repository zilf-ai sudah di-clone di komputer kamu

### Instalasi CLI

**PowerShell (Windows):**

```powershell
# Step 1 — Install CLI secara global
npm install -g @zilf-ai/cli

# Step 2 — Tambahkan Python Scripts ke PATH (jika belum)
$env:PATH += ";C:\Users\<username>\AppData\Local\Python\pythoncore-3.14-64\Scripts"

# Step 3 — Install Python dependencies (pertama kali saja)
pip install -r "C:\path\to\zilf-ai\requirements.txt"

# Step 4 — Set path ke folder project zilf-ai
$env:ZILF_PATH = "C:\path\to\zilf-ai"

# Step 5 — Jalankan!
zilf
```

> **Ganti** `C:\path\to\zilf-ai` dengan path aktual folder hasil clone di komputer kamu.
> Contoh: `D:\2026\Workspace\Website\.zilf.ai`

### Buat PATH permanen (agar tidak perlu set ulang setiap restart)

```powershell
# Buka PowerShell profile
notepad $PROFILE

# Tambahkan dua baris ini ke dalam file, lalu simpan:
$env:PATH += ";C:\Users\<username>\AppData\Local\Python\pythoncore-3.14-64\Scripts"
$env:ZILF_PATH = "C:\path\to\zilf-ai"
```

### Perintah CLI

```powershell
# Mode chat interaktif (default)
zilf

# Jalankan satu task langsung
zilf run "Buatkan fungsi Python untuk sorting bubble sort"

# Lihat daftar tools yang tersedia
zilf tools

# Cek status backend
zilf status

# Tampilkan output Python (untuk debug)
zilf --verbose

# Gunakan port custom
zilf --port 9000
```

### Contoh Sesi Chat

```
PS C:\Users\LENOVO> zilf

zilf.ai — AI Coding Agent

✔ zilf.ai ready — port 8000

  Type your task and press Enter. Type "exit" to quit.

› Buatkan REST API sederhana dengan FastAPI

  Baik, saya akan membuat REST API dengan FastAPI...
  [agent bekerja...]

› exit

  Goodbye.
```

---

## 🚀 Penggunaan

### Jalankan Agent

```bash
# Pastikan Ollama berjalan terlebih dahulu
ollama serve

# Jalankan basic agent
python examples/basic_agent.py

# Atau dengan task custom
python examples/basic_agent.py "Buat fungsi Python untuk sorting bubble sort"

# Mode demo (tanpa Ollama)
python examples/basic_agent.py --demo
```

### Via CLI Python

```bash
# Jalankan task
python -m agent.main run "Fix the failing tests in auth.py"

# Gunakan provider tertentu
python -m agent.main run "Add type hints" --provider groq --model llama3-70b-8192

# Mode verbose
python -m agent.main run "Refactor utils.py" --verbose
```

### Via API (FastAPI)

```bash
# Jalankan server
uvicorn agent.api:app --host 0.0.0.0 --port 8000 --reload

# Kirim task
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{"task": "Write a binary search function in Python"}'
```

---

## 🔌 Perbandingan Provider

| Provider | Model | Kecepatan | Biaya | Privasi | Rekomendasi |
|----------|-------|-----------|-------|---------|-------------|
| **Ollama** | deepseek-coder | ⭐⭐⭐ | Gratis | ✅ Lokal | Coding ringan |
| **Ollama** | llama3 | ⭐⭐⭐ | Gratis | ✅ Lokal | General purpose |
| **Ollama** | codellama | ⭐⭐⭐ | Gratis | ✅ Lokal | Coding berat |
| **Groq** | llama3-70b-8192 | ⭐⭐⭐⭐⭐ | Gratis* | ☁️ Cloud | Tercepat |
| **Groq** | mixtral-8x7b | ⭐⭐⭐⭐⭐ | Gratis* | ☁️ Cloud | Reasoning |
| **Gemini** | gemini-1.5-flash | ⭐⭐⭐⭐ | Gratis* | ☁️ Cloud | Multimodal |
| **Gemini** | gemini-1.5-pro | ⭐⭐⭐⭐ | $3.5/1M | ☁️ Cloud | Kompleks |

*Gratis dengan batasan free tier

---

## 🏗️ Arsitektur

```
┌─────────────────────────────────────────────┐
│                  Zilf AI                     │
│                                             │
│  ┌──────────┐    ┌──────────────────────┐   │
│  │  CLI /   │───▶│      Agent Core      │   │
│  │  API     │    │  (ReAct Loop)        │   │
│  └──────────┘    └──────────┬───────────┘   │
│                             │               │
│              ┌──────────────▼────────────┐  │
│              │        LLM Router         │  │
│              │  Ollama │ Groq │ Gemini   │  │
│              └──────────────┬────────────┘  │
│                             │               │
│         ┌───────────────────▼────────────┐  │
│         │          Tool Registry          │  │
│         │  📁 File  💻 Terminal  🔍 Web   │  │
│         │  🐍 Code  🗂️ Search   ➕ More  │  │
│         └───────────────────┬────────────┘  │
│                             │               │
│                    ┌────────▼────────┐      │
│                    │  Docker Sandbox  │      │
│                    │   (Isolated)     │      │
│                    └─────────────────┘      │
└─────────────────────────────────────────────┘
```

---

## 📁 Struktur Project

```
zilf-ai/
├── agent/                  ← Source code utama
│   ├── core/               ← Agent, reasoning loop, state
│   ├── llm/                ← Provider: Ollama, Groq, Gemini
│   ├── tools/              ← 8 built-in tools
│   ├── memory/             ← Short-term & long-term memory
│   ├── sandbox/            ← Docker isolation
│   └── prompts/            ← System & task prompts
├── cli/                    ← npm CLI (@zilf-ai/cli)
│   ├── bin/zilf.js         ← Entry point CLI
│   └── lib/                ← client, server, installer
├── config/                 ← YAML configuration
├── examples/               ← Contoh penggunaan
├── tests/                  ← Unit & integration tests
├── observability/          ← Tracing & dashboard
├── security/               ← Audit log & sandboxing
├── deployment/             ← Docker & VS Code extension
└── docs/                   ← Dokumentasi
```

---

## 🧪 Testing

```bash
# Jalankan semua unit test
pytest tests/unit/ -v

# Jalankan smoke test
python examples/hello_world_task.py

# Jalankan dengan coverage
pytest tests/ --cov=agent --cov-report=html
```

---

## 🤝 Kontribusi

Kontribusi sangat disambut! Zilf AI adalah project open source dan kami senang menerima kontribusi dari siapapun.

### Cara Berkontribusi

1. **Fork** repository ini
2. **Buat branch** untuk fitur kamu:
   ```bash
   git checkout -b feature/nama-fitur
   ```
3. **Commit** perubahan kamu:
   ```bash
   git commit -m "feat: tambah fitur xyz"
   ```
4. **Push** ke branch kamu:
   ```bash
   git push origin feature/nama-fitur
   ```
5. **Buat Pull Request** ke branch `main`

### Panduan Kontribusi

- Ikuti format commit: `feat:`, `fix:`, `docs:`, `refactor:`
- Pastikan semua test lulus sebelum PR
- Tambahkan test untuk fitur baru
- Update dokumentasi jika diperlukan

### Area yang Butuh Kontribusi

- 🌐 Terjemahan dokumentasi
- 🧪 Penambahan test coverage
- 🔌 Provider LLM baru (Mistral API, Cohere, dll)
- 🛠️ Tool baru (database, browser automation, dll)
- 📊 Peningkatan dashboard observability

---

## 🗺️ Roadmap

### v0.1.0 — Foundation ✅
- [x] ReAct reasoning loop
- [x] Multi-provider LLM (Ollama, Groq, Gemini)
- [x] 8 built-in tools
- [x] Docker sandbox isolation
- [x] FastAPI server
- [x] VS Code extension
- [x] npm CLI (`@zilf-ai/cli`)

### v0.2.0 — Memory & Intelligence 🚧
- [ ] Long-term memory dengan ChromaDB
- [ ] Task planning yang lebih cerdas
- [ ] Context window optimization
- [ ] Loop detection yang lebih baik

### v0.3.0 — Multi-Agent 📋
- [ ] Supervisor + Worker architecture
- [ ] Parallel task execution
- [ ] Agent communication protocol
- [ ] Shared memory antar agent

### v0.4.0 — Ecosystem 📋
- [ ] Plugin system untuk tools custom
- [ ] Web UI dashboard
- [ ] Integrasi GitHub Actions
- [ ] Support lebih banyak IDE (JetBrains, Neovim)

---

## 📄 Lisensi

Zilf AI dilisensikan di bawah [MIT License](LICENSE).

Copyright (c) 2025 Zilf AI Contributors

---

## 🙏 Acknowledgments

- [Ollama](https://ollama.com) — Local LLM runtime
- [Groq](https://groq.com) — Ultra-fast LLM inference
- [Google AI Studio](https://aistudio.google.com) — Gemini API
- [Tavily](https://tavily.com) — AI-optimized web search
- [LangChain](https://langchain.com) — Inspirasi arsitektur agent
- [SWE-bench](https://github.com/princeton-nlp/SWE-bench) — Benchmark evaluasi

---

<div align="center">

Dibuat dengan ❤️ oleh [Alfiz Ilham](https://github.com/alfizilham)

⭐ **Star repo ini jika Zilf AI bermanfaat untukmu!** ⭐

</div>