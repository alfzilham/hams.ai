# ============================================================
# AI Coding Agent — Sandbox Image
# Multi-stage build for minimal attack surface.
#
# Build:  docker build -f docker/Dockerfile -t ai-coding-agent-sandbox .
# ============================================================

# ---- Stage 1: builder ----
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build tools (needed for some packages like chromadb)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt


# ---- Stage 2: runtime sandbox ----
FROM python:3.12-slim AS sandbox

LABEL maintainer="ai-coding-agent"
LABEL description="Isolated sandbox for AI agent code execution"

WORKDIR /workspace

# Runtime-only system packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Create restricted sandbox user — no sudo, no home write access
RUN groupadd --gid 1001 sandbox && \
    useradd --uid 1001 --gid sandbox \
            --no-create-home \
            --shell /bin/bash \
            --comment "Sandbox execution user" \
            sandbox

# Create workspace dir and hand ownership to sandbox user
RUN mkdir -p /workspace /tmp/sandbox && \
    chown -R sandbox:sandbox /workspace /tmp/sandbox

# Copy agent source (read-only reference — not executed from here)
COPY --chown=root:root agent/ /agent_src/

# Hardening: drop write access to everywhere except /workspace and /tmp
RUN chmod -R 555 /agent_src

# Switch to non-root user
USER sandbox

# Runtime environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp/sandbox \
    TMPDIR=/tmp/sandbox

WORKDIR /workspace

# Entrypoint delegates to sandbox_entrypoint.sh (set at runtime)
CMD ["/bin/bash"]
