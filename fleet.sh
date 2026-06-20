#!/usr/bin/env bash
# fleet — one entry point for the WSL side of the hua-mcp fleet.
# Everything this project needs is in this repo; this is the documented way to run it.
#
#   ./fleet.sh doctor      check the toolchain (uv / node / pm2 / nix)
#   ./fleet.sh up          start all WSL servers under PM2 (ecosystem.config.js)
#   ./fleet.sh down        stop & remove them from PM2
#   ./fleet.sh restart     restart all
#   ./fleet.sh status      pm2 list
#   ./fleet.sh logs [name] pm2 logs (optionally one app)
#   ./fleet.sh health      curl /health on every WSL-hosted server (from registry.json)
#   ./fleet.sh config      print client .mcp.json (from registry.json)
#   ./fleet.sh autostart   persist PM2 + print the boot-survival command
#
# Windows side (win-agents:8001) is separate: run win_agents/install-autostart.ps1
# once on the Windows host.
set -euo pipefail
cd "$(dirname "$0")"

PY=python3

_wsl_ports() {  # ports of servers hosted on WSL, from the registry
  $PY -c "import json;[print(s['port']) for s in json.load(open('registry.json'))['servers'] if s.get('host_os')=='wsl']"
}
_names() {
  $PY -c "import json;[print(s['name'],s['port']) for s in json.load(open('registry.json'))['servers'] if s.get('host_os')=='wsl']"
}

cmd="${1:-help}"; shift || true
case "$cmd" in
  doctor)
    ok=1
    for t in uv node pm2; do
      if command -v "$t" >/dev/null 2>&1; then echo "  ✓ $t -> $(command -v $t)"; else echo "  ✗ $t MISSING"; ok=0; fi
    done
    if command -v nix >/dev/null 2>&1 || [ -x /nix/var/nix/profiles/default/bin/nix ]; then echo "  ✓ nix (for md2pdf)"; else echo "  ✗ nix MISSING (md2pdf needs it)"; ok=0; fi
    [ $ok = 1 ] && echo "toolchain OK" || { echo "install the missing tools first"; exit 1; }
    ;;
  up)        pm2 start ecosystem.config.js ;;
  down)      pm2 delete ecosystem.config.js || pm2 delete all ;;
  restart)   pm2 restart ecosystem.config.js ;;
  status)    pm2 ls ;;
  logs)      pm2 logs ${1:-} ;;
  health)
    echo "fleet health (WSL-hosted):"
    while read -r name port; do
      if curl -fsS --max-time 4 "http://localhost:$port/health" >/dev/null 2>&1; then
        echo "  ✓ $name  :$port  $(curl -fsS http://localhost:$port/health)"
      else
        echo "  ✗ $name  :$port  DOWN"
      fi
    done < <(_names)
    echo "(win-agents:8001 lives on the Windows host — check there)"
    ;;
  config)    $PY shared/gen_config.py ;;
  autostart)
    pm2 save
    echo "Now run 'pm2 startup' and execute the sudo line it prints, so the fleet survives reboot."
    ;;
  help|*)
    sed -n '2,20p' "$0"
    ;;
esac
