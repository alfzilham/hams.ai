#!/bin/bash
# ============================================================
# Sandbox Entrypoint
# Runs as sandbox user (uid 1001), applies ulimits, then
# executes the command passed in.
#
# Usage (set as Docker CMD or docker run override):
#   docker run ... ai-coding-agent-sandbox bash sandbox_entrypoint.sh python script.py
# ============================================================

set -euo pipefail

# ---- Hard resource limits ----
# Max CPU time per process: 30 seconds
ulimit -t 30

# Max file size: 50 MB
ulimit -f 51200

# Max open files: 256
ulimit -n 256

# Max processes / threads: 64
ulimit -u 64

# Max virtual memory: 512 MB
ulimit -v 524288

# Disable core dumps
ulimit -c 0

# ---- Verify we are NOT root ----
if [ "$(id -u)" -eq 0 ]; then
    echo "[sandbox] ERROR: refusing to run as root" >&2
    exit 1
fi

echo "[sandbox] Running as uid=$(id -u) gid=$(id -g)"
echo "[sandbox] Workdir: $(pwd)"
echo "[sandbox] Command: $*"

# ---- Execute the provided command ----
exec "$@"
