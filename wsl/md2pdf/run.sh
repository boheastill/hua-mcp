#!/usr/bin/env bash
# md2pdf launcher — used by PM2 (and runnable by hand).
# Enters the Nix dev shell (Chromium + CJK fonts + Node), ensures deps, then serves.
set -euo pipefail
cd "$(dirname "$0")"

NIX="${NIX:-/nix/var/nix/profiles/default/bin/nix}"

exec "$NIX" develop -c bash -c '
  set -euo pipefail
  UV="/home/bohea/.local/bin/uv"
  [ -d .venv ] || "$UV" venv .venv
  req=requirements.txt; [ -f requirements.lock ] && req=requirements.lock
  VIRTUAL_ENV="$PWD/.venv" "$UV" pip install -q -r "$req"
  [ -d node_modules ] || { [ -f package-lock.json ] && npm ci --no-audit --no-fund || npm install --no-audit --no-fund; }
  export PATH="/nix/store/gq9hcb85prkd6gsghzfmil6rbcf8xq9a-nodejs-slim-22.22.3/bin:$PATH"
  exec .venv/bin/python server.py
'
