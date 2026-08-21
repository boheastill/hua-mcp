#!/usr/bin/env bash
# MCP launcher (PM2 / manual). Ensures venv+deps, serves its registry port.
set -euo pipefail
export PATH="/home/bohea/.local/bin:/usr/local/bin:$PATH"
cd "$(dirname "$0")"
unset NODE_CHANNEL_FD
[ -d .venv ] || uv venv .venv
req=requirements.txt; [ -f requirements.lock ] && req=requirements.lock
VIRTUAL_ENV="$PWD/.venv" uv pip install -q -r "$req"
exec .venv/bin/python server.py
