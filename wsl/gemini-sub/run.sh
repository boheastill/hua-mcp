#!/usr/bin/env bash
# 订阅额度 OpenAI 兼容桥 (antigravity-auth)。非 MCP, pm2 直接托管。
set -euo pipefail
unset NODE_CHANNEL_FD
[ -d .venv ] || uv venv .venv
exec .venv/bin/python -m uvicorn antigravity_auth.api_server.api:app --host 127.0.0.1 --port 8120
