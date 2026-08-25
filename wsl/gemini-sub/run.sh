#!/usr/bin/env bash
# 订阅额度 OpenAI 兼容桥 (antigravity-auth)。非 MCP, pm2 直接托管。
set -euo pipefail
unset NODE_CHANNEL_FD
[ -d .venv ] || uv venv .venv
exec .venv/bin/python -m uvicorn antigravity_auth.api_server.api:app --host 127.0.0.1 --port 8120
# ⚠️ 2026-08-25: 8120 已划给舰队 printctl。本桥当前停用; 复活前先改下方端口
# (如 8124)并同步 ~/.dsh/settings.yaml 的 gemini-sub provider, 见 OPS_NOTES §八。
