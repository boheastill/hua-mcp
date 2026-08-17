#!/usr/bin/env bash
# local-model MCP launcher (PM2 / manual)
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || uv venv .venv
req=requirements.txt; [ -f requirements.lock ] && req=requirements.lock
VIRTUAL_ENV="$PWD/.venv" uv pip install -q -r "$req"
exec .venv/bin/python server.py
