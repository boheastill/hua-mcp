#!/usr/bin/env bash
# MCP launcher (PM2 / manual). Ensures venv+deps, serves its registry port.
set -euo pipefail
cd "$(dirname "$0")"
# PM2 injects NODE_CHANNEL_FD (its IPC pipe fd); a node spawned by any tool would
# inherit it, try to use the dead fd, and SIGABRT. Strip it defensively.
unset NODE_CHANNEL_FD
[ -d .venv ] || uv venv .venv
req=requirements.txt; [ -f requirements.lock ] && req=requirements.lock
VIRTUAL_ENV="$PWD/.venv" uv pip install -q -r "$req"
exec .venv/bin/python server.py
