# ============================================================
# Hams AI — Production App Image
# Runs the FastAPI API server (agent/api.py) via uvicorn.
#
# Build:  docker build -f docker/Dockerfile.app -t hams-ai-app .
# Run:    docker-compose -f deployment/docker-compose.prod.yml up
# ============================================================

# ---- Stage 1: builder ----
FROM python:3.14-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml requirements.txt ./

# Install only production deps (no dev extras)
RUN pip install --user --no-cache-dir -e "." || \
    pip install --user --no-cache-dir -r requirements.txt


# ---- Stage 2: runtime ----
FROM python:3.14-slim AS app

LABEL maintainer="alfizilham51@outlook.com"
LABEL description="Hams AI — production API server"
LABEL version="0.1.0"

WORKDIR /app

# Runtime system packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Create non-root user
RUN groupadd --gid 1001 appuser && \
    useradd --uid 1001 --gid appuser \
            --no-create-home \
            --shell /bin/bash \
            appuser

# Copy source code
COPY --chown=appuser:appuser agent/     /app/agent/
COPY --chown=appuser:appuser config/    /app/config/
COPY --chown=appuser:appuser prompts/   /app/prompts/ 2>/dev/null || true

# Create runtime directories
RUN mkdir -p /app/workspace /app/logs && \
    chown -R appuser:appuser /app/workspace /app/logs

USER appuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

EXPOSE 8000

# Health check — hits /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:8000/health || exit 1

# Start uvicorn
CMD ["python", "-m", "uvicorn", "agent.api:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--log-level", "info"]
