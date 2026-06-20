#!/usr/bin/env bash
# md2pdf launcher — used by PM2 (and runnable by hand).
# Enters the Nix dev shell (Chromium + CJK fonts + Node), ensures deps, then serves.
set -euo pipefail
cd "$(dirname "$0")"

NIX="${NIX:-/nix/var/nix/profiles/default/bin/nix}"

exec "$NIX" develop -c bash -c '
  set -euo pipefail
  [ -d .venv ] || uv venv .venv
  VIRTUAL_ENV="$PWD/.venv" uv pip install -q -r requirements.txt
  [ -d node_modules ] || npm install --no-audit --no-fund
  exec .venv/bin/python server.py --http
'
