#!/usr/bin/env bash
# Cloud API agent server launcher (used by PM2). Ensures venv+deps, serves :8003.
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || uv venv .venv
VIRTUAL_ENV="$PWD/.venv" uv pip install -q -r requirements.txt
exec .venv/bin/python api_mcp_server.py --http
