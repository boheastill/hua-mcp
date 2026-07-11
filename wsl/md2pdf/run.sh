#!/usr/bin/env bash
# md2pdf launcher — used by PM2 (and runnable by hand).
# Enters the Nix dev shell (Chromium + CJK fonts + Node), ensures deps, then serves.
set -euo pipefail
cd "$(dirname "$0")"

# PM2 injects NODE_CHANNEL_FD (its IPC pipe fd) into children. Any node we spawn
# later (puppeteer print.js, mmdc) inherits it, tries to use that dead fd, and
# SIGABRTs. Strip it here so child node processes start clean.
unset NODE_CHANNEL_FD

NIX="${NIX:-/nix/var/nix/profiles/default/bin/nix}"

exec "$NIX" develop -c bash -c '
  set -euo pipefail
  [ -d .venv ] || uv venv .venv
  req=requirements.txt; [ -f requirements.lock ] && req=requirements.lock
  VIRTUAL_ENV="$PWD/.venv" uv pip install -q -r "$req"
  [ -d node_modules ] || { [ -f package-lock.json ] && npm ci --no-audit --no-fund || npm install --no-audit --no-fund; }
  exec .venv/bin/python server.py
'
