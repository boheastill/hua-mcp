#!/usr/bin/env bash
# fleet — one entry point for the hua-mcp fleet (WSL side).
# Truth = each MCP's mcp.json (win/<name>/, wsl/<name>/). Everything is discovered by
# scanning, so adding/removing an MCP needs no edit here.
#
#   ./fleet.sh doctor      check toolchain (uv / node / pm2 / nix)
#   ./fleet.sh list        list discovered MCPs (name / port / os)
#   ./fleet.sh validate    lint every mcp.json (keys, unique ports, band, files) — exits 1 on error
#   ./fleet.sh test        per-MCP import smoke (venv + `import server`); --live also boots + /health
#   ./fleet.sh up          PM2-start every wsl MCP (one process each)
#   ./fleet.sh down        stop & remove them from PM2
#   ./fleet.sh restart     restart all
#   ./fleet.sh status      pm2 list
#   ./fleet.sh logs [name] pm2 logs (optionally one app)
#   ./fleet.sh health      curl /health on every MCP
#   ./fleet.sh config      print client .mcp.json (scans mcp.json)
#   ./fleet.sh autostart   persist PM2 + print the boot-survival command
#   ./fleet.sh new <wsl|win> <name>   scaffold a new MCP (auto-assigns a free port)
#   ./fleet.sh install-claude         register every MCP into Claude Code (user scope)
#   ./fleet.sh install-clients        register every MCP into ALL clients (Claude/Codex/agy/dsh/ZCode) — idempotent
#   ./fleet.sh install-hooks          enable the git pre-commit guardrail (hooks/)
#   ./fleet.sh sync                   up + pm2 save + install-clients + health (make ALL wsl MCPs live everywhere)
set -euo pipefail
cd "$(dirname "$0")"
PY=python3

# Emit "name port os dir heavy" for every real MCP (skips _-prefixed dirs).
_mcps() {
  $PY - <<'PY'
import json, pathlib
for mf in sorted(pathlib.Path('.').glob('*/*/mcp.json')):
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
    for t in uv node pm2; do command -v "$t" >/dev/null 2>&1 && echo "  ✓ $t" || { echo "  ✗ $t MISSING"; ok=0; }; done
    { command -v nix >/dev/null 2>&1 || [ -x /nix/var/nix/profiles/default/bin/nix ]; } && echo "  ✓ nix (md2pdf)" || { echo "  ✗ nix MISSING"; ok=0; }
    [ $ok = 1 ] && echo "toolchain OK" || { echo "install the missing tools first"; exit 1; }
    ;;

  list)
    printf "%-12s %-6s %-5s %s\n" NAME PORT OS DIR
    _mcps | while read -r name port os dir heavy; do printf "%-12s %-6s %-5s %s\n" "$name" "$port" "$os" "$dir"; done
    ;;

  validate)
    $PY - <<'PY' || exit 1
import json, pathlib, sys
errors, warns, seen_ports = [], [], {}
mans = [m for m in pathlib.Path('.').glob('*/*/mcp.json') if not any(p.startswith('_') for p in m.parts)]
if not mans:
    print("no MCPs found (expected win/<name>/mcp.json or wsl/<name>/mcp.json)"); sys.exit(1)
for mf in sorted(mans):
    d = mf.parent
    try:
        m = json.loads(mf.read_text(encoding='utf-8'))
    except Exception as e:
        errors.append(f"{mf}: invalid JSON ({e})"); continue
    for k in ("name", "port", "os"):
        if k not in m: errors.append(f"{d}: mcp.json missing required key '{k}'")
    name, port, os_ = m.get("name"), m.get("port"), m.get("os")
    if os_ not in ("win", "wsl"): errors.append(f"{d}: os must be 'win' or 'wsl', got {os_!r}")
    if name and name != d.name: warns.append(f"{d}: name {name!r} != dir {d.name!r} (convention: match)")
    if isinstance(port, int):
        if port in seen_ports: errors.append(f"{d}: port {port} also used by {seen_ports[port]}")
        seen_ports[port] = str(d)
        band_ok = (os_ == "win" and 8001 <= port <= 8099) or (os_ == "wsl" and 8100 <= port <= 8999)
        if not band_ok: warns.append(f"{d}: port {port} outside band (win 8001-8099 / wsl 8100-8999)")
    else:
        errors.append(f"{d}: port must be an int, got {port!r}")
    if not (d / "server.py").exists(): errors.append(f"{d}: missing server.py")
    if not (d / "requirements.txt").exists(): errors.append(f"{d}: missing requirements.txt")
    launcher = "run.ps1" if os_ == "win" else "run.sh"
    if not (d / launcher).exists(): errors.append(f"{d}: missing {launcher}")
# .ps1 must be ASCII: Windows PowerShell 5.1 reads files as the system ANSI codepage
# (e.g. GBK) and non-ASCII bytes corrupt the script ("string missing terminator").
for ps in pathlib.Path('.').rglob('*.ps1'):
    if '.venv' in ps.parts or 'node_modules' in ps.parts: continue
    try: ps.read_bytes().decode('ascii')
    except UnicodeDecodeError: errors.append(f"{ps}: non-ASCII char (breaks Windows PowerShell 5.1) - use ASCII only")
for w in warns: print(f"  ⚠ {w}")
for e in errors: print(f"  ✗ {e}")
print(f"validate: {len(mans)} MCP(s), {len(errors)} error(s), {len(warns)} warning(s)")
sys.exit(1 if errors else 0)
PY
    ;;

  test)
    live=0; [ "${1:-}" = "--live" ] && live=1
    echo "== validate ==" ; "$0" validate || exit 1
    echo "== import smoke =="
    fail=0
    # include _template so the thing agents copy is also checked
    dirs=$(_mcps | awk '{print $3" "$4}'); dirs="wsl _template
$dirs"
    printf '%s\n' "$dirs" | while read -r os dir; do
      [ -z "${dir:-}" ] && continue
      ( cd "$dir"
        [ -d .venv ] || uv venv .venv >/dev/null 2>&1
        req=requirements.txt; [ -f requirements.lock ] && req=requirements.lock
        VIRTUAL_ENV="$PWD/.venv" uv pip install -q -r "$req" >/dev/null 2>&1
        if .venv/bin/python -c "import server" >/tmp/hua_test.$$.log 2>&1; then
          echo "  ✓ import $dir"
        else
          echo "  ✗ import $dir"; sed 's/^/      /' /tmp/hua_test.$$.log | tail -5; touch /tmp/hua_fail.$$
        fi
        rm -f /tmp/hua_test.$$.log )
    done
    [ -f /tmp/hua_fail.$$ ] && { rm -f /tmp/hua_fail.$$; echo "import smoke: FAIL"; exit 1; } || echo "import smoke: PASS"
    if [ "$live" = 1 ]; then
      echo "== live /health (wsl MCPs) =="
      "$0" up >/dev/null 2>&1 || true
      sleep 3; "$0" health
    fi
    ;;

  up)
    _mcps | while read -r name port os dir heavy; do
      [ "$os" = "wsl" ] || { echo "skip $name (os=$os, starts on Windows)"; continue; }
      mem=500M; [ "$heavy" = "1" ] && mem=1G
      app="mcp-$name-$port"
      if pm2 describe "$app" >/dev/null 2>&1; then pm2 restart "$app"
      else pm2 start "$dir/run.sh" --name "$app" --interpreter none --max-memory-restart "$mem"; fi
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
        # npm-native members (e.g. browser) have no /health route: probe /mcp with
        # an MCP initialize instead — any HTTP answer < 5xx means the server is alive.
        code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 4 -X POST "http://localhost:$port/mcp" \
          -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
          -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"fleet-health","version":"0"}}}') || code=000
        if [ "${code:-000}" -ge 200 ] 2>/dev/null && [ "${code:-000}" -lt 500 ] 2>/dev/null; then
          echo "  ✓ $name :$port ($os)  alive via /mcp initialize (no /health endpoint)"
        else
          echo "  ✗ $name :$port ($os)  DOWN$([ "$os" = win ] && echo ' (runs on Windows host)')"
        fi
      fi
    done
    ;;
  config)    $PY gen_config.py ;;
  autostart) pm2 save; echo "Now run 'pm2 startup' and execute the sudo line it prints." ;;

  new)
    os="${1:-}"; name="${2:-}"
    { [ "$os" = wsl ] || [ "$os" = win ]; } && [ -n "$name" ] || { echo "usage: ./fleet.sh new <wsl|win> <name>"; exit 1; }
    dest="$os/$name"
    [ -e "$dest" ] && { echo "✗ $dest already exists"; exit 1; }
    port=$($PY - "$os" <<'PY'
import json, pathlib, sys
os_ = sys.argv[1]
used = {json.loads(m.read_text())['port'] for m in pathlib.Path('.').glob('*/*/mcp.json')}
lo, hi = (8001, 8099) if os_ == 'win' else (8100, 8999)
print(next(p for p in range(lo, hi + 1) if p not in used))
PY
)
    cp -r _template "$dest"
    rm -rf "$dest/.venv" "$dest/__pycache__"  # build artifacts only — keep requirements.lock (the pinned mcp SDK is the whole point)
    [ "$os" = wsl ] && rm -f "$dest/run.ps1" || rm -f "$dest/run.sh"
    $PY - "$dest" "$name" "$os" "$port" <<'PY'
import json, sys
d, name, os_, port = sys.argv[1:5]
p = f"{d}/mcp.json"; m = json.load(open(p))
m.update(name=name, os=os_, port=int(port), public=False, desc=f"TODO: describe {name}")
json.dump(m, open(p, "w"), indent=2, ensure_ascii=False); open(p, "a").write("\n")
PY
    echo "✓ created $dest on port $port"
    echo "  next: edit $dest/server.py (write @mcp.tool()), then ./fleet.sh validate && ./fleet.sh test"
    ;;

  install-claude)
    _mcps | while read -r name port os dir heavy; do
      claude mcp remove "$name" -s user >/dev/null 2>&1 || true
      claude mcp add --transport http "$name" "http://localhost:$port/mcp" -s user && echo "  + $name -> :$port"
    done
    echo "registered at user scope. Check: claude mcp list"
    ;;

  install-hooks)
    git config core.hooksPath hooks && chmod +x hooks/* 2>/dev/null
    echo "✓ git hooks enabled (core.hooksPath=hooks). pre-commit now runs ./fleet.sh validate."
    ;;

  install-clients)
    # One command to refresh every client's fleet wiring. Idempotent — safe to
    # re-run after adding/removing members or changing ports.
    #   Claude  ~/.claude.json                    (remove+add per member)
    #   Codex   ~/.codex/config.toml              (remove+add per member)
    #   agy     ~/.gemini/config/mcp_config.json  (add = add-or-update)
    #   dsh     ~/.dsh/profiles/*/cordis.patch.yml (dsh-mcp-client block fully
    #           regenerated -> stale fleet entries cleaned; other patches/comments kept)
    #   ZCode   ~/.zcode/cli/config.json mcp.servers (add/update by name only)
    echo "== Claude Code =="
    "$0" install-claude
    echo "== Codex =="
    if command -v codex >/dev/null 2>&1; then
      _mcps | while read -r name port os dir heavy; do
        codex mcp remove "$name" >/dev/null 2>&1 || true
        codex mcp add --url "http://localhost:$port/mcp" "$name" >/dev/null 2>&1 \
          && echo "  + $name -> :$port" || echo "  ✗ $name (codex add failed)"
      done
    else
      echo "  (codex not on PATH, skip)"
    fi
    echo "== agy =="
    if command -v agy >/dev/null 2>&1; then
      _mcps | while read -r name port os dir heavy; do
        agy mcp add "$name" "http://localhost:$port/mcp" >/dev/null 2>&1 \
          && echo "  + $name -> :$port" || echo "  ✗ $name (agy add failed)"
      done
    else
      echo "  (agy not on PATH, skip)"
    fi
    echo "== dsh (regenerate the dsh-mcp-client block in every profile) =="
    if command -v dsh >/dev/null 2>&1 && [ -d "$HOME/.dsh/profiles" ]; then
      $PY - <<'PY'
import glob, json, pathlib
members = sorted(
    (int(m["port"]), m["name"])
    for mf in pathlib.Path(".").glob("*/*/mcp.json")
    if not any(p.startswith("_") for p in mf.parts)
    for m in [json.loads(mf.read_text(encoding="utf-8"))]
)
lines = ["- insert:"]
for port, name in members:
    lines += [
        f"  - id: mcp-{name}",
        "    name: '@deepseek-ai/dsh-mcp-client'",
        "    config:",
        f"      serverName: {name}",
        "      transport: streamable-http",
        f"      url: http://localhost:{port}/mcp",
    ]
for pf in glob.glob(str(pathlib.Path.home() / ".dsh/profiles/*/cordis.patch.yml")):
    p = pathlib.Path(pf)
    old = p.read_text(encoding="utf-8").splitlines()
    starts = [i for i, l in enumerate(old) if l.startswith("- ")]
    spans = [(s, starts[k + 1] if k + 1 < len(starts) else len(old)) for k, s in enumerate(starts)]
    # every top-level block that carries dsh-mcp-client entries is fleet-owned:
    # drop them all, then insert one regenerated block where the first one lived
    hits = [(s, e) for s, e in spans if any("dsh-mcp-client" in old[i] for i in range(s, e))]
    if hits:
        drop = {i for s, e in hits for i in range(s, e)}
        kept = [l for i, l in enumerate(old) if i not in drop]
        at = hits[0][0]
        sep = [""] if len(kept) > at and kept[at].startswith("- ") else []
        new = kept[:at] + lines + sep + kept[at:]
        action = f"regenerated {len(hits)} block(s) merged" if len(hits) > 1 else "regenerated"
    else:
        new = (old + [""] + lines) if old and old[-1].strip() else old + lines
        action = "appended"
    p.write_text("\n".join(new) + "\n", encoding="utf-8")
    print(f"  {p.parent.name}: {action}, {len(members)} entries")
print(f"  expected dsh-mcp-client count per profile: {len(members)}")
PY
      for pf in "$HOME"/.dsh/profiles/*/cordis.patch.yml; do
        prof=$(basename "$(dirname "$pf")")
        cnt=$(dsh --profile "$prof" --dump-config 2>/dev/null | grep -c dsh-mcp-client || true)
        echo "  verify $prof --dump-config: $cnt dsh-mcp-client entries"
      done
      echo "  (dsh loads the patch only at startup — restart the profile to pick changes up)"
    else
      echo "  (dsh not on PATH or ~/.dsh/profiles missing, skip)"
    fi
    echo "== ZCode (~/.zcode/cli/config.json -> mcp.servers) =="
    if [ -d "$HOME/.zcode/cli" ]; then
      $PY - <<'PY'
import json, pathlib
members = sorted(
    (int(m["port"]), m["name"])
    for mf in pathlib.Path(".").glob("*/*/mcp.json")
    if not any(p.startswith("_") for p in mf.parts)
    for m in [json.loads(mf.read_text(encoding="utf-8"))]
)
p = pathlib.Path.home() / ".zcode/cli/config.json"
cfg = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
servers = cfg.setdefault("mcp", {}).setdefault("servers", {})
for port, name in members:
    servers[name] = {"type": "http", "url": f"http://localhost:{port}/mcp"}
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"  mcp.servers: {len(members)} fleet entries written (add/update only, no auto-removal)")
PY
    else
      echo "  (~/.zcode/cli not found, skip)"
    fi
    echo "done. Claude/Codex/agy/ZCode pick tools up in NEW sessions; dsh needs a profile restart."
    ;;

  sync)
    # Make every wsl MCP live the same way (no per-MCP special-casing):
    # start under PM2 -> persist for boot -> register with every client -> health.
    "$0" up
    pm2 save >/dev/null 2>&1 || true
    "$0" install-clients
    "$0" health
    ;;

  help|*)    sed -n '2,26p' "$0" ;;
esac
