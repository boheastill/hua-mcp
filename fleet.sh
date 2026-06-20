#!/usr/bin/env bash
# fleet — one entry point for the WSL side of the hua-mcp fleet.
# Truth = each MCP's mcp.json (win/<name>/, wsl/<name>/). This script discovers them
# by scanning, so adding an MCP needs no edit here.
#
#   ./fleet.sh doctor      check toolchain (uv / node / pm2 / nix)
#   ./fleet.sh list        list all discovered MCPs (name / port / os)
#   ./fleet.sh up          PM2-start every wsl MCP (one process each)
#   ./fleet.sh down        stop & remove them from PM2
#   ./fleet.sh restart     restart all
#   ./fleet.sh status      pm2 list
#   ./fleet.sh logs [name] pm2 logs (optionally one app)
#   ./fleet.sh health      curl /health on every MCP (from its mcp.json)
#   ./fleet.sh config      print client .mcp.json (scans mcp.json)
#   ./fleet.sh autostart   persist PM2 + print the boot-survival command
#
# Windows side (os=win) is separate: run win/install-autostart.ps1 once on Windows.
set -euo pipefail
cd "$(dirname "$0")"
PY=python3

# Emit "name port os dir heavy" for every real MCP (skips _-prefixed dirs).
_mcps() {
  $PY - <<'PY'
import json, pathlib
root = pathlib.Path('.')
for mf in sorted(root.glob('*/*/mcp.json')):
    if any(p.startswith('_') for p in mf.parts):
        continue
    m = json.loads(mf.read_text(encoding='utf-8'))
    print(m['name'], m['port'], m.get('os','wsl'), str(mf.parent), '1' if m.get('heavy') else '0')
PY
}

cmd="${1:-help}"; shift || true
case "$cmd" in
  doctor)
    ok=1
    for t in uv node pm2; do
      if command -v "$t" >/dev/null 2>&1; then echo "  ✓ $t"; else echo "  ✗ $t MISSING"; ok=0; fi
    done
    if command -v nix >/dev/null 2>&1 || [ -x /nix/var/nix/profiles/default/bin/nix ]; then echo "  ✓ nix (md2pdf)"; else echo "  ✗ nix MISSING"; ok=0; fi
    [ $ok = 1 ] && echo "toolchain OK" || { echo "install the missing tools first"; exit 1; }
    ;;
  list)
    printf "%-12s %-6s %-5s %s\n" NAME PORT OS DIR
    _mcps | while read -r name port os dir heavy; do printf "%-12s %-6s %-5s %s\n" "$name" "$port" "$os" "$dir"; done
    ;;
  up)
    _mcps | while read -r name port os dir heavy; do
      [ "$os" = "wsl" ] || { echo "skip $name (os=$os, starts on Windows)"; continue; }
      mem=500M; [ "$heavy" = "1" ] && mem=1G
      app="mcp-$name-$port"
      if pm2 describe "$app" >/dev/null 2>&1; then
        pm2 restart "$app"
      else
        pm2 start "$dir/run.sh" --name "$app" --interpreter none --max-memory-restart "$mem"
      fi
    done
    ;;
  down)      _mcps | while read -r name port os dir heavy; do pm2 delete "mcp-$name-$port" 2>/dev/null || true; done ;;
  restart)   pm2 restart all ;;
  status)    pm2 ls ;;
  logs)      pm2 logs ${1:-} ;;
  health)
    echo "fleet health:"
    _mcps | while read -r name port os dir heavy; do
      if curl -fsS --max-time 4 "http://localhost:$port/health" >/dev/null 2>&1; then
        echo "  ✓ $name :$port ($os)  $(curl -fsS http://localhost:$port/health)"
      else
        echo "  ✗ $name :$port ($os)  DOWN${os:+ }$([ "$os" = win ] && echo '(runs on Windows host)')"
      fi
    done
    ;;
  config)    $PY gen_config.py ;;
  autostart)
    pm2 save
    echo "Now run 'pm2 startup' and execute the sudo line it prints, so the fleet survives reboot."
    ;;
  help|*)    sed -n '2,21p' "$0" ;;
esac
