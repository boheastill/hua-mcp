#!/usr/bin/env bash
# WSL agent server launcher (used by PM2). Ensures venv+deps, serves :8002.
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || uv venv .venv
VIRTUAL_ENV="$PWD/.venv" uv pip install -q -r requirements.txt
exec .venv/bin/python wsl_mcp_server.py --http
