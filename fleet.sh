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
#   ./fleet.sh install-clients [--dry-run]  preview/apply registration into ALL clients (Claude/Codex/agy/dsh/ZCode) — idempotent
#   ./fleet.sh verify            protocol-level E2E: MCP initialize + tools/list on every member
#   ./fleet.sh secrets           audit key files members depend on (existence + 0600 perms)
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

# _mcps filtered by the optional mcp.json "clients" list (no key = all clients).
# Used by every registration path; scan-only consumers keep using _mcps.
_mcps_c() {
  $PY - "$1" <<'PY'
import json, pathlib, sys
client = sys.argv[1]
for mf in sorted(pathlib.Path('.').glob('*/*/mcp.json')):
    if any(p.startswith('_') for p in mf.parts):
        continue
    m = json.loads(mf.read_text(encoding='utf-8'))
    if m.get('clients') and client not in m['clients']:
        continue
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
    cl = m.get("clients")
    if cl is not None:
        if not isinstance(cl, list) or not cl:
            errors.append(f"{d}: 'clients' must be a non-empty list")
        else:
            bad = [c for c in cl if c not in ("claude", "codex", "agy", "dsh", "zcode")]
            if bad: warns.append(f"{d}: unknown clients {bad} (known: claude codex agy dsh zcode)")
    secrets = m.get("secrets")
    if secrets is not None:
        if not isinstance(secrets, list):
            errors.append(f"{d}: 'secrets' must be a list")
        else:
            for s in secrets:
                if not isinstance(s, dict) or not (s.get("env") or s.get("path")):
                    warns.append(f"{d}: secrets entry needs 'env' and/or 'path'")
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

  verify)
    # Protocol-level E2E: real MCP initialize + tools/list against every member.
    # Catches "process up but tools broken" that /health cannot see (bad venv,
    # broken tool code, dead upstream for relays). Read-only — never restarts
    # members, so it is safe to run while clients hold live sessions.
    $PY - <<'PY'
import json, pathlib, re, sys, urllib.error, urllib.request

def post(url, body, headers=None, timeout=45):
    data = json.dumps(body).encode()
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, dict(r.headers), r.read().decode("utf-8", "replace")

def data_of(raw):
    m = re.search(r"data: ?(\{.*)", raw)
    if m:
        return json.loads(m.group(1))
    return json.loads(raw) if raw.strip().startswith("{") else None

members = []
for mf in sorted(pathlib.Path(".").glob("*/*/mcp.json")):
    if any(p.startswith("_") for p in mf.parts):
        continue
    m = json.loads(mf.read_text(encoding="utf-8"))
    members.append((m["name"], int(m["port"]), m.get("os", "wsl")))

fail = skip = ok = 0
for name, port, os_ in members:
    if os_ != "wsl":
        skip += 1
        print(f"  = {name} :{port} ({os_}) skipped (starts on Windows host)")
        continue
    url = f"http://localhost:{port}/mcp"
    # one retry: relay upstreams (Cloudflare etc.) and PTY-based members (agy
    # cold-starts its CLI) both have transient first-touch failures
    for attempt in (1, 2):
        try:
            st, hdrs, raw = post(url, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-03-26", "capabilities": {},
                "clientInfo": {"name": "fleet-verify", "version": "0"}}})
            d = data_of(raw)
            if st != 200 or not d or "result" not in d:
                raise RuntimeError(f"initialize HTTP {st}: {raw[:120]}")
            sid = next((v for k, v in hdrs.items() if k.lower() == "mcp-session-id"), None)
            if sid:
                try:
                    post(url, {"jsonrpc": "2.0", "method": "notifications/initialized"},
                         {"mcp-session-id": sid}, timeout=15)
                except Exception:
                    pass
            _, _, raw2 = post(url, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                              ({"mcp-session-id": sid} if sid else None))
            d2 = data_of(raw2)
            tools = [t["name"] for t in d2["result"]["tools"]] if d2 and "result" in d2 else []
            if not tools:
                raise RuntimeError(f"tools/list returned no tools: {raw2[:120]}")
            info = d["result"].get("serverInfo", {}).get("name", "")
            shown = ", ".join(tools[:4]) + ("…" if len(tools) > 4 else "")
            suffix = f"  [{info}]" if info else ""
            if attempt == 2:
                suffix += "  (ok on retry)"
            print(f"  ✓ {name} :{port}  tools={len(tools)} ({shown}){suffix}")
            ok += 1
            break
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code} from member/upstream"
        except urllib.error.URLError as e:
            err = f"unreachable ({e.reason}) — ./fleet.sh up?"
        except Exception as e:  # noqa: BLE001 — report, don't crash the sweep
            err = str(e)
        if attempt == 1:
            import time
            time.sleep(2)
    else:
        fail += 1
        print(f"  ✗ {name} :{port}  {err}")
print(f"verify: {ok} ok, {fail} failed, {skip} skipped")
sys.exit(1 if fail else 0)
PY
    ;;

  secrets)
    # Audit secrets members depend on: env override set? key file present?
    # mode 0600? Metadata = optional "secrets" list in mcp.json entries
    # {env, path, optional?, note?}; mcp.json "auth_env" is auto-included as
    # optional (inbound auth). Exit 1 when a required secret is missing/loose.
    $PY - <<'PY'
import json, os, pathlib, sys

bad = 0
for mf in sorted(pathlib.Path(".").glob("*/*/mcp.json")):
    if any(p.startswith("_") for p in mf.parts):
        continue
    m = json.loads(mf.read_text(encoding="utf-8"))
    entries = list(m.get("secrets") or [])
    if m.get("auth_env"):
        entries.append({"env": m["auth_env"], "optional": True,
                        "note": "inbound auth (mcp.json auth_env)"})
    if not entries:
        continue
    for s in entries:
        env, path = s.get("env"), s.get("path")
        opt = s.get("optional")
        note = f" — {s['note']}" if s.get("note") else ""
        if env and os.environ.get(env):
            print(f"  ✓ {m['name']}: {env} set from environment{note}")
            continue
        if not path:
            msg = f"  ⚠ {m['name']}: {env or '?'} not set, no key file declared{note}"
            print(msg + (" (optional)" if opt else ""))
            if not opt:
                bad += 1
            continue
        p = pathlib.Path(path).expanduser()
        if not p.exists():
            if opt:
                print(f"  ○ {m['name']}: {path} not set (optional){note}")
            else:
                print(f"  ✗ {m['name']}: {path} missing, {env or 'no env'} unset{note}")
                bad += 1
            continue
        mode = oct(p.stat().st_mode & 0o777)
        strict = mode == "0o600"
        if not strict and not opt:
            bad += 1
        print(f"  {'✓' if strict else '⚠'} {m['name']}: {path} exists, mode={mode}{note}")
print(f"secrets: {'FAIL' if bad else 'OK'} ({bad} problem(s))")
sys.exit(1 if bad else 0)
PY
    ;;

  _plan_install_clients)
    # Read-only diff of "what install-clients would change" per client config.
    $PY - <<'PY'
import json, pathlib, re

HOME = pathlib.Path.home()
KNOWN = ("claude", "codex", "agy", "dsh", "zcode")

def desired(client):
    out = {}
    for mf in pathlib.Path(".").glob("*/*/mcp.json"):
        if any(p.startswith("_") for p in mf.parts):
            continue
        m = json.loads(mf.read_text(encoding="utf-8"))
        if m.get("clients") and client not in m["clients"]:
            continue
        out[m["name"]] = f"http://localhost:{m['port']}/mcp"
    return out

def fleetish(url):
    return bool(re.match(r"^http://localhost:8\d{3}/mcp$", url or ""))

targets = {}
try:
    d = json.loads((HOME / ".claude.json").read_text())
    targets["claude"] = {k: v.get("url", "") for k, v in (d.get("mcpServers") or {}).items() if isinstance(v, dict)}
except Exception:
    targets["claude"] = None
try:
    import tomllib
    t = tomllib.loads((HOME / ".codex/config.toml").read_text())
    targets["codex"] = {k: v.get("url", "") for k, v in (t.get("mcp_servers") or {}).items() if isinstance(v, dict)}
except Exception:
    targets["codex"] = None
try:
    g = json.loads((HOME / ".gemini/config/mcp_config.json").read_text())
    targets["agy"] = {k: v.get("serverUrl", "") for k, v in (g.get("mcpServers") or {}).items() if isinstance(v, dict)}
except Exception:
    targets["agy"] = None
try:
    z = json.loads((HOME / ".zcode/cli/config.json").read_text())
    targets["zcode"] = {k: v.get("url", "") for k, v in (z.get("mcp", {}).get("servers") or {}).items() if isinstance(v, dict)}
except Exception:
    targets["zcode"] = None
try:
    import yaml

    class _L(yaml.SafeLoader):  # cordis patch allows !!js expressions — ignore unknown tags
        pass
    _L.add_multi_constructor("tag:yaml.org,2002:js", lambda loader, suffix, node: None)
    _L.add_multi_constructor("!", lambda loader, suffix, node: None)

    for prof in ("web", "headless"):
        text = (HOME / f".dsh/profiles/{prof}/cordis.patch.yml").read_text()
        names = {}
        doc = yaml.load(text, Loader=_L) or []
        def walk(o):
            if isinstance(o, dict):
                if o.get("name") == "@deepseek-ai/dsh-mcp-client":
                    c = o.get("config") or {}
                    names[c.get("serverName", "?")] = c.get("url", "")
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(doc)
        if not names:  # loader still failed -> textual fallback (we generate this block ourselves)
            names = dict(re.findall(r"serverName: (\S+)\s*\n\s*transport: streamable-http\s*\n\s*url: (\S+)", text))
        targets[f"dsh:{prof}"] = names or None
except Exception:
    targets["dsh:web"] = targets["dsh:headless"] = None

LABEL = {
    "claude": "Claude  ~/.claude.json",
    "codex": "Codex   ~/.codex/config.toml",
    "agy": "agy     ~/.gemini/config/mcp_config.json",
    "dsh:web": "dsh     web patch",
    "dsh:headless": "dsh     headless patch",
    "zcode": "ZCode   ~/.zcode/cli/config.json",
}
for key in ("claude", "codex", "agy", "dsh:web", "dsh:headless", "zcode"):
    want = desired(key.split(":")[0])
    cur = targets.get(key)
    if cur is None:
        print(f"  {LABEL[key]}: {len(want)} desired — config unreadable!")
        continue
    add = {k: v for k, v in want.items() if k not in cur}
    upd = {k: (cur[k], v) for k, v in want.items() if k in cur and cur[k] != v}
    stale = {k: v for k, v in cur.items() if k not in want and fleetish(v)}
    extra = [k for k in cur if k not in want and not fleetish(cur[k])]
    print(f"  {LABEL[key]}: {len(want)} desired | +{len(add)} ~{len(upd)} stale-fleet:{len(stale)} non-fleet:{len(extra)}")
    for k, v in add.items():
        print(f"      + {k} {v}")
    for k, (old, new) in upd.items():
        print(f"      ~ {k} {old} -> {new}")
    for k, v in stale.items():
        auto = "dsh auto-cleans" if key.startswith("dsh") else "remove manually if decommissioned"
        print(f"      - {k} {v} (stale fleet entry; {auto})")
PY
    ;;

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
    _mcps_c claude | while read -r name port os dir heavy; do
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
    # Members with mcp.json "clients": [...] are only registered to those clients.
    # --dry-run prints the change plan without writing anything.
    echo "== plan (desired vs current) =="
    "$0" _plan_install_clients
    if [ "${1:-}" = "--dry-run" ]; then
      echo "(dry-run: nothing written)"
      exit 0
    fi
    echo "== Claude Code =="
    "$0" install-claude
    echo "== Codex =="
    if command -v codex >/dev/null 2>&1; then
      _mcps_c codex | while read -r name port os dir heavy; do
        codex mcp remove "$name" >/dev/null 2>&1 || true
        codex mcp add --url "http://localhost:$port/mcp" "$name" >/dev/null 2>&1 \
          && echo "  + $name -> :$port" || echo "  ✗ $name (codex add failed)"
      done
    else
      echo "  (codex not on PATH, skip)"
    fi
    echo "== agy =="
    if command -v agy >/dev/null 2>&1; then
      _mcps_c agy | while read -r name port os dir heavy; do
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
members = []
for mf in pathlib.Path(".").glob("*/*/mcp.json"):
    if any(p.startswith("_") for p in mf.parts):
        continue
    m = json.loads(mf.read_text(encoding="utf-8"))
    if m.get("clients") and "dsh" not in m["clients"]:
        continue
    members.append((int(m["port"]), m["name"]))
members.sort()
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
members = []
for mf in pathlib.Path(".").glob("*/*/mcp.json"):
    if any(p.startswith("_") for p in mf.parts):
        continue
    m = json.loads(mf.read_text(encoding="utf-8"))
    if m.get("clients") and "zcode" not in m["clients"]:
        continue
    members.append((int(m["port"]), m["name"]))
members.sort()
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
