"""vpn MCP -- manage the network proxy (sing-box) for the agent.

CRITICAL CONTEXT (read this first, every time):
  You are a domestic Chinese AI model. You do NOT need the proxy to function.
  When the proxy is down, you are STILL fully operational -- only the user's
  access to foreign websites is broken. The user may be panicking (e.g. mid
  video call). Your job: fix the network silently and report when done.
  The user does NOT need to do anything unless you explicitly ask them to.

WHAT THIS MCP DOES:
  Provides tools to diagnose, restart, reconfigure, and switch nodes for the
  Windows network proxy (sing-box). You manage the network through these tools.
  You do NOT need to touch the filesystem or run shell commands -- but you CAN
  if the tools are not enough (e.g. SSH to check server status).

WHAT IS SING-BOX:
  sing-box is a universal proxy platform running as a Windows service ("singbox").
  It intercepts all traffic via a TUN adapter (172.19.0.1) and routes it based on
  rules: direct for domestic/whitelisted sites, proxy (via Singapore VPS) for
  everything else. The Clash-compatible API at 127.0.0.1:9090 exposes status.

CONFIG FILE:
  C:\\Users\\bohea\\sing-box\\config.json -- the sing-box routing/outbound/DNS config.
  Architecture documentation: D:\\vpn-configs\\architecture.md

SERVERS:
  - SG (47.130.65.208): Primary. Hysteria2 (UDP 443) + SS2022 (TCP 8443).
  - US (66.154.101.110): Backup. SS2022 (TCP 8443). Sometimes goes down.
  - Azure (52.146.92.1): Emergency. WireGuard (UDP 51820). Last resort.
  SSH: ssh -i D:/ssh-keys/lbqg.pem <user>@<ip>
  (SG: user=admin, US: user=root, Azure: user=bohea)

PROXY GROUPS:
  - sg-auto (URLTest): Auto-selects between hy2-sg and ss-sg by latency.
  - agent-group (Selector): For AI agents. Defaults to agent-sg. Can switch to agent-us.

TOOLS:
  1. vpn_status            -- see current state (which node, service running?)
  2. vpn_connectivity_test -- actually test internet (not just API)
  3. vpn_restart           -- atomic restart + verify
  4. vpn_switch_node       -- quick-switch to a different outbound node
  5. vpn_logs              -- read recent error logs
  6. vpn_config            -- read current config
  7. vpn_route_test        -- predict if a domain goes direct or proxy
  8. vpn_config_write      -- write config (with validation, does NOT restart)
  9. vpn_apply             -- write config + restart (one-shot)

EMERGENCY PROCEDURE (user says network is down):
  Step 1: vpn_connectivity_test()
    - api_ok + proxy_ok + direct_ok  => all good, maybe browser issue
    - api_ok + !proxy_ok + direct_ok => proxy node dead, go to Step 2
    - api_ok + !proxy_ok + !direct_ok => TUN broken, go to Step 2
    - !api_ok + !proxy_ok + direct_ok => sing-box crashed, go to Step 2

  Step 2: vpn_restart()
    - ok=True  => done, tell user "fixed, reconnect your call"
    - ok=False => go to Step 3

  Step 3: vpn_connectivity_test() again
    - proxy_ok=True => fixed
    - proxy_ok=False => go to Step 4

  Step 4: vpn_switch_node(target="ss-sg")  (force TCP instead of UDP)
    - Then vpn_connectivity_test()
    - proxy_ok=True => done
    - proxy_ok=False => vpn_switch_node(target="agent-us")  (try US)
    - proxy_ok=True => done
    - proxy_ok=False => go to Step 5

  Step 5: SSH to check servers
    - ssh admin@47.130.65.208 and check: ss -tlnp | grep -E '443|8443'
    - If server is down, restart the service on the server
    - If server is up but unreachable from China, go to Step 6

  Step 6: Last resort -- tell user
    "All proxy servers are unreachable. You need to act:
     Option A: Open D:\\ssh-keys\\azure-au-wg.conf in WireGuard, connect
     Option B: Use phone hotspot as temporary internet
     Option C: sc stop singbox && connect OpenVPN (D:\\vpn-configs\\us-openvpn-tcp.ovpn)"

  RULES:
    - NEVER retry the same broken node more than twice. Escalate.
    - You have ~3 minutes before the user's video call fully drops.
    - Be concise. "Fixed" is better than "I restarted the service successfully."
    - If you need the user to do something, give ONE clear instruction.

TYPICAL WORKFLOW -- add a domain to proxy:
  1. cfg = vpn_config()
  2. vpn_route_test(domain="example.com")          # confirm it currently goes direct
  3. Add "example.com" to cfg["route"]["rules"][...]["domain_suffix"]
  4. vpn_apply(config_json=json.dumps(cfg))         # write + restart + verify
  5. vpn_route_test(domain="example.com")           # confirm it now goes to sg-auto

DESIGN PRINCIPLE:
  Agent manages the network entirely through these tools, never touching the
  filesystem or running shell commands directly. Every write is validated and
  backed up. Every restart is self-verifying. The agent is ALWAYS available
  (domestic model, no proxy needed) and should fix things silently.
"""
import json
import os
import pathlib
import socket
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

import requests

for _p in pathlib.Path(__file__).resolve().parents:
    if (_p / "huamcp.py").exists():
        sys.path.insert(0, str(_p))
        break
import huamcp  # noqa: E402

SERVICE = "singbox"
CLASH_API = "http://127.0.0.1:9090"
CACHE_DB = os.path.expanduser("~\\sing-box\\cache.db")
LOG_FILE = os.path.expanduser("~\\sing-box\\sing-box.log")
CONFIG_FILE = os.path.expanduser("~\\sing-box\\config.json")

mcp = huamcp.server(__file__)


# -- helpers ------------------------------------------------------------------

def _service_state() -> str:
    """Query Windows service state via 'sc query'. Returns 'running'/'stopped'/'unknown'."""
    try:
        r = subprocess.run(
            ["sc", "query", SERVICE], capture_output=True, text=True, timeout=10
        )
        if "RUNNING" in r.stdout:
            return "running"
        if "STOPPED" in r.stdout:
            return "stopped"
    except Exception:
        pass
    return "unknown"


def _clash_get(path: str, timeout: float = 4) -> Optional[dict]:
    """GET from Clash API (127.0.0.1:9090). Returns parsed JSON or None on failure."""
    try:
        r = requests.get(f"{CLASH_API}{path}", timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def _load_config() -> Optional[dict]:
    """Load and parse config.json. Returns dict or None on error."""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _domain_matches(domain: str, suffixes: List[str]) -> bool:
    """Check if domain matches any suffix (exact or subdomain)."""
    d = domain.lower()
    for s in suffixes:
        s = s.lower()
        if d == s or d.endswith("." + s):
            return True
    return False


def _ip_in_cidr(ip: str, cidrs: List[str]) -> bool:
    """Check if an IP is within any CIDR range."""
    import ipaddress
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for cidr in cidrs:
        try:
            if addr in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


def _simulate_route(config: dict, domain: str = "", ip: str = "") -> Dict[str, Any]:
    """Simulate sing-box sequential rule matching. Returns predicted outbound + matched rule.

    Limitations: process_name rules and rule_set (geosite-cn) are skipped.
    """
    rules = config.get("route", {}).get("rules", [])

    resolved_ip = ip
    if domain and not ip:
        try:
            resolved_ip = socket.gethostbyname(domain)
        except socket.gaierror:
            resolved_ip = ""

    for rule in rules:
        outbound = rule.get("outbound")
        if not outbound:
            continue

        if rule.get("ip_is_private") and resolved_ip:
            import ipaddress
            try:
                if ipaddress.ip_address(resolved_ip).is_private:
                    return {"outbound": outbound, "rule": "ip_is_private", "matched": True}
            except ValueError:
                pass

        if rule.get("process_name"):
            continue

        if rule.get("domain_suffix") and domain:
            if _domain_matches(domain, rule["domain_suffix"]):
                return {"outbound": outbound, "rule": f"domain_suffix ({len(rule['domain_suffix'])} entries)", "matched": True}

        if rule.get("ip_cidr") and resolved_ip:
            if _ip_in_cidr(resolved_ip, rule["ip_cidr"]):
                return {"outbound": outbound, "rule": f"ip_cidr ({len(rule['ip_cidr'])} ranges)", "matched": True}

        if rule.get("rule_set"):
            continue

    final = config.get("route", {}).get("final", "sg-auto")
    return {"outbound": final, "rule": "final (default)", "matched": True}


# -- tools --------------------------------------------------------------------

@mcp.tool()
def vpn_restart() -> Dict[str, Any]:
    """Atomically restart sing-box and verify it's alive.

    Steps: stop service -> wait 3s for TUN release -> delete poisoned cache.db ->
    start service -> poll Clash API up to 5 times.

    When to call:
      - After editing config.json manually
      - When the network is wedged (no connectivity, API unreachable)
      - First attempt when network goes down

    Returns:
      ok (bool): True if Clash API answered within 15s.
      sc_start_ok (bool): Whether sc start returned success.
      steps (list[str]): Human-readable log of what happened.
      hint (str|None): Error guidance if ok=False.

    If ok=False twice in a row, DO NOT retry -- switch nodes instead.
    """
    steps: List[str] = []

    try:
        stop = subprocess.run(["sc", "stop", SERVICE], capture_output=True, text=True, timeout=20)
        steps.append(f"stop: {(stop.stdout or stop.stderr).strip()[:120]}")
    except Exception as e:
        steps.append(f"stop error: {e}")

    time.sleep(3)

    if os.path.exists(CACHE_DB):
        try:
            os.remove(CACHE_DB)
            steps.append("cleared cache.db")
        except OSError as e:
            steps.append(f"cache.db remove failed: {e}")

    start_ok = False
    try:
        start = subprocess.run(["sc", "start", SERVICE], capture_output=True, text=True, timeout=60)
        out = (start.stdout or start.stderr).strip()
        steps.append(f"start: {out[:120]}")
        start_ok = start.returncode == 0 or "START_PENDING" in out or "RUNNING" in out
    except Exception as e:
        steps.append(f"start error: {e}")

    time.sleep(3)

    verified = False
    for attempt in range(5):
        try:
            r = requests.get(f"{CLASH_API}/version", timeout=4)
            if r.status_code == 200:
                verified = True
                steps.append(f"api ok (attempt {attempt + 1})")
                break
        except Exception:
            steps.append(f"api wait {attempt + 1}/5...")
            time.sleep(2)

    return {
        "ok": verified,
        "sc_start_ok": start_ok,
        "steps": steps,
        "hint": None if verified else (
            f"Restart failed. Try manually: sc stop {SERVICE} && sc start {SERVICE}. "
            "If still broken, use vpn_switch_node to try a different server, "
            "or check vpn_logs(level='ERROR') for root cause."
        ),
    }


@mcp.tool()
def vpn_status() -> Dict[str, Any]:
    """Query current VPN/proxy status: service state, proxy groups, selected nodes.

    When to call:
      - Before making changes (know the current state)
      - After vpn_restart or vpn_apply (verify recovery)
      - When diagnosing "which server am I going through?"

    Returns:
      service (str): "running", "stopped", or "unknown".
      api_reachable (bool): Whether Clash API (127.0.0.1:9090) responded.
      version (str|null): sing-box version string.
      groups (dict): Proxy groups, each with:
        - type: "Selector" (manual pick) or "URLTest" (auto-pick by latency)
        - selected (str): Currently active outbound name (e.g. "hy2-sg")
        - options (list[str]): Available outbound names in this group

    Example return:
      {
        "service": "running",
        "groups": {
          "sg-auto": {"type": "URLTest", "selected": "hy2-sg", "options": ["hy2-sg", "ss-sg"]},
          "agent-group": {"type": "Selector", "selected": "agent-sg", "options": ["agent-sg", "agent-us"]}
        }
      }
    """
    state = _service_state()
    groups: Dict[str, Any] = {}

    proxies = _clash_get("/proxies")
    if proxies:
        for name, info in proxies.get("proxies", {}).items():
            ptype = info.get("type", "")
            if ptype in ("Selector", "URLTest"):
                groups[name] = {
                    "type": ptype,
                    "selected": info.get("now", "?"),
                    "options": info.get("all", []),
                }

    version = _clash_get("/version")
    return {
        "service": state,
        "api_reachable": version is not None,
        "version": version.get("version") if version else None,
        "groups": groups,
    }


@mcp.tool()
def vpn_connectivity_test() -> Dict[str, Any]:
    """Test actual internet connectivity through the proxy. Not just API -- real traffic.

    When to call:
      - FIRST thing when network goes down (before restarting)
      - After vpn_restart to confirm recovery
      - To distinguish "proxy node down" from "TUN adapter broken" from "DNS broken"

    Tests performed:
      1. Clash API reachable (local control plane)
      2. Google via proxy (confirms proxy path works end-to-end)
      3. Baidu direct (confirms direct path works, TUN is functional)

    Returns:
      api_ok (bool): Clash API responded.
      proxy_ok (bool): Could reach google.com through proxy (status 200).
      direct_ok (bool): Could reach baidu.com directly (status 200).
      diagnosis (str): Plain-language diagnosis of what's broken.

    Interpretation:
      - api_ok=True, proxy_ok=True, direct_ok=True  => Network is fine
      - api_ok=True, proxy_ok=False, direct_ok=True => Proxy node dead, need to switch
      - api_ok=True, proxy_ok=False, direct_ok=False => TUN adapter broken, need restart
      - api_ok=False, proxy_ok=False, direct_ok=True => sing-box service crashed
      - api_ok=False, proxy_ok=False, direct_ok=False => System network issue, not sing-box
    """
    results = {}

    # Test 1: Clash API
    try:
        r = requests.get(f"{CLASH_API}/version", timeout=4)
        results["api_ok"] = r.status_code == 200
    except Exception:
        results["api_ok"] = False

    # Test 2: Google via proxy
    try:
        r = requests.get("https://www.google.com", timeout=8,
                         proxies={"https": "http://127.0.0.1:7890"})
        results["proxy_ok"] = r.status_code == 200
    except Exception:
        results["proxy_ok"] = False

    # Test 3: Baidu direct
    try:
        r = requests.get("https://www.baidu.com", timeout=5)
        results["direct_ok"] = r.status_code == 200
    except Exception:
        results["direct_ok"] = False

    # Diagnosis
    api, proxy, direct = results["api_ok"], results["proxy_ok"], results["direct_ok"]
    if api and proxy and direct:
        diag = "Network is healthy. All paths working."
    elif api and not proxy and direct:
        diag = "Proxy node is dead (SG server unreachable). Use vpn_switch_node to try US or restart."
    elif api and not proxy and not direct:
        diag = "TUN adapter broken. Use vpn_restart to reinitialize."
    elif not api and not proxy and direct:
        diag = "sing-box service crashed. Use vpn_restart."
    elif not api and not proxy and not direct:
        diag = "System network issue. Check WiFi/Ethernet, not sing-box."
    else:
        diag = "Partial connectivity. Check vpn_logs for details."

    results["diagnosis"] = diag
    return results


@mcp.tool()
def vpn_logs(lines: int = 30, level: Optional[str] = None) -> Dict[str, Any]:
    """Read recent sing-box log lines.

    When to call:
      - Diagnosing why the network is slow or broken
      - Checking if a config change caused errors
      - Looking for specific failures (TIME_WAIT spikes, connection resets)

    Args:
      lines: Number of tail lines to return (default 30, max 200).
      level: Filter by level, e.g. "ERROR", "WARN". None = all levels.

    Returns:
      ok (bool): Whether log file was readable.
      total_in_file (int): Total lines in log file.
      returned (int): Number of lines in this response.
      lines (list[str]): The log lines, newest last.

    Log format: "+0800 YYYY-MM-DD HH:MM:SS LEVEL [id duration] module: message"
    Common errors:
      - "connection upload closed" + "forcibly closed by remote host" = server dropped connection
      - "i/o timeout" on direct = domestic service unreachable
      - "dial tcp ... actively refused it" = remote port not listening (node down)
      - "connection download closed" = proxy node stopped responding
    """
    lines = min(max(lines, 1), 200)

    if not os.path.exists(LOG_FILE):
        return {"ok": False, "error": f"Log file not found: {LOG_FILE}", "lines": []}

    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
    except OSError as e:
        return {"ok": False, "error": str(e), "lines": []}

    if level:
        level_upper = level.upper()
        all_lines = [l for l in all_lines if level_upper in l.upper()]

    tail = all_lines[-lines:]
    return {
        "ok": True,
        "total_in_file": len(all_lines),
        "returned": len(tail),
        "lines": [l.rstrip("\n\r") for l in tail],
    }


@mcp.tool()
def vpn_config() -> Dict[str, Any]:
    """Read the current sing-box config.json.

    When to call:
      - Before vpn_config_write or vpn_apply (know what you're changing)
      - To audit current routing rules
      - To check which domains go direct vs proxy

    Returns:
      ok (bool): Whether config was readable.
      path (str): Absolute path to config.json.
      summary (dict): Quick overview:
        - route_rules (int): Number of route rules
        - outbounds (list[str]): All outbound tags
        - dns_servers (list[tuple]): [(tag, server_address), ...]
        - final_outbound (str): Default outbound for unmatched traffic
      config (dict): The full parsed config.json.

    Config structure (sing-box format):
      - dns.servers: DNS resolvers (dns-remote via proxy, dns-direct for CN)
      - inbounds: TUN adapter (172.19.0.1) + mixed proxy (0.0.0.0:7890)
      - outbounds: Protocol nodes (hy2-sg, ss-sg, agent-sg, agent-us) + groups
      - route.rules: Ordered rules (match first wins). Key types:
        - process_name: Match by process (LOL=direct, claude=agent-group)
        - domain_suffix: Match by domain (google.com=proxy, microsoft.com=direct)
        - ip_cidr: Match by IP range (Google IPs=proxy, CN ISP IPs=direct)
        - final: Default (sg-auto = proxy via Singapore)
    """
    config = _load_config()
    if config is None:
        return {"ok": False, "error": f"Cannot read config: {CONFIG_FILE}"}

    route_rules = config.get("route", {}).get("rules", [])
    outbounds = [o.get("tag", "?") for o in config.get("outbounds", [])]
    dns_servers = [(d.get("tag"), d.get("server")) for d in config.get("dns", {}).get("servers", [])]

    return {
        "ok": True,
        "path": CONFIG_FILE,
        "summary": {
            "route_rules": len(route_rules),
            "outbounds": outbounds,
            "dns_servers": dns_servers,
            "final_outbound": config.get("route", {}).get("final"),
        },
        "config": config,
    }


@mcp.tool()
def vpn_config_write(config_json: str, validate_only: bool = False) -> Dict[str, Any]:
    """Write a new sing-box config.json with validation.

    When to call:
      - After reading config with vpn_config and modifying it
      - Use validate_only=True first to check before writing
      - Does NOT restart -- call vpn_restart or vpn_apply for that

    Args:
      config_json: The full config as a JSON string (use json.dumps on modified dict).
      validate_only: If true, only validate without writing (dry run).

    Validation checks:
      - Valid JSON (parseable)
      - Has required sections: route, outbounds, dns
      - route.final references a valid outbound tag

    Returns:
      ok (bool): Whether validation passed (and write succeeded if not dry run).
      written (str): Path to config.json (if written).
      backup (str): Path to config.json.bak (if backup was created).
      errors (list[str]): Validation failures (if any).
    """
    try:
        config = json.loads(config_json)
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"Invalid JSON: {e}"}

    errors = []
    if "route" not in config:
        errors.append("missing 'route' section")
    if "outbounds" not in config:
        errors.append("missing 'outbounds' section")
    if "dns" not in config:
        errors.append("missing 'dns' section")
    if config.get("route", {}).get("final") not in [o.get("tag") for o in config.get("outbounds", [])]:
        errors.append(f"route.final '{config.get('route',{}).get('final')}' not in outbounds")

    if errors:
        return {"ok": False, "errors": errors}

    if validate_only:
        return {"ok": True, "valid": True, "note": "dry run -- nothing written"}

    backup = CONFIG_FILE + ".bak"
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                old = f.read()
            with open(backup, "w", encoding="utf-8") as f:
                f.write(old)
    except OSError:
        pass

    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except OSError as e:
        return {"ok": False, "error": f"Write failed: {e}"}

    return {"ok": True, "written": CONFIG_FILE, "backup": backup}


@mcp.tool()
def vpn_apply(config_json: str) -> Dict[str, Any]:
    """Atomically write config + restart + verify. The one-shot "make it so" tool.

    When to call:
      - When you want to change config AND have it take effect immediately
      - This is the preferred way to apply config changes

    Args:
      config_json: The full config as a JSON string.

    Steps: validate -> write config.json -> restart sing-box -> poll API -> verify.
    If write fails, restart is skipped. If restart fails, config is already written
    (use vpn_restart to retry).

    Returns:
      ok (bool): True if both write and restart succeeded.
      write (dict): Result from vpn_config_write.
      restart (dict): Result from vpn_restart.
    """
    write_result = vpn_config_write(config_json, validate_only=False)
    if not write_result.get("ok"):
        return {"ok": False, "phase": "write", **write_result}

    restart_result = vpn_restart()

    return {
        "ok": restart_result.get("ok", False),
        "phase": "restart",
        "write": write_result,
        "restart": restart_result,
    }


@mcp.tool()
def vpn_switch_node(target: str = "sg-auto") -> Dict[str, Any]:
    """Quick-switch a proxy group to a different outbound node (no config change needed).

    When to call:
      - Current node is dead but sing-box is running (vpn_connectivity_test shows
        proxy_ok=False but api_ok=True)
      - Want to force traffic through a specific server
      - Emergency fallback during video call outage

    Args:
      target: The outbound or group to switch to. Options:
        - "sg-auto" (default): Auto-select between hy2-sg and ss-sg
        - "ss-sg": Force Singapore SS2022 (TCP, more stable than Hy2)
        - "hy2-sg": Force Singapore Hysteria2 (UDP, faster when stable)
        - "agent-us": Route through US server (66.154.101.110)
        - "agent-sg": Route through Singapore with h2mux (for agent traffic)

    How it works: Calls the Clash API to switch the selector group's active node.
    This is TEMPORARY -- it does not modify config.json. Changes are lost on restart.

    Returns:
      ok (bool): Whether the switch was acknowledged by the API.
      target (str): The node switched to.
      note (str): Reminder that this is temporary.

    For permanent changes, use vpn_apply to modify config.json instead.
    """
    # Map friendly names to their group and target
    node_map = {
        "sg-auto": {"group": "sg-auto", "target": "sg-auto"},
        "ss-sg": {"group": "sg-auto", "target": "ss-sg"},
        "hy2-sg": {"group": "sg-auto", "target": "hy2-sg"},
        "agent-us": {"group": "agent-group", "target": "agent-us"},
        "agent-sg": {"group": "agent-group", "target": "agent-sg"},
    }

    if target not in node_map:
        return {
            "ok": False,
            "error": f"Unknown target '{target}'. Valid options: {list(node_map.keys())}",
        }

    info = node_map[target]
    group = info["group"]
    node = info["target"]

    try:
        r = requests.put(
            f"{CLASH_API}/proxies/{group}",
            json={"name": node},
            timeout=4,
        )
        ok = r.status_code == 204
    except Exception as e:
        return {"ok": False, "error": str(e)}

    return {
        "ok": ok,
        "target": target,
        "group": group,
        "note": "Temporary switch. Lost on restart. Use vpn_apply for permanent changes.",
    }


@mcp.tool()
def vpn_route_test(domain: str = "", ip: str = "") -> Dict[str, Any]:
    """Predict which outbound a domain or IP would use based on current config rules.

    When to call:
      - Before adding/removing a domain from routing rules
      - To verify a config change had the intended effect
      - To diagnose "why is this site slow?" (check if it goes proxy or direct)

    Args:
      domain: Domain to test (e.g. "google.com", "live.com", "example.com").
      ip: IP address to test (e.g. "8.8.8.8", "20.190.148.166").
          If only domain is given, it will be resolved to an IP.

    Returns:
      ok (bool): Whether the test ran.
      domain (str): The domain tested.
      ip (str): The IP tested (or "(resolved)" if auto-resolved).
      outbound (str): Predicted outbound tag (e.g. "sg-auto", "direct", "agent-group").
      rule (str): Which rule matched (e.g. "domain_suffix (24 entries)", "ip_is_private").
      matched (bool): Always True (falls through to 'final' if no specific rule matches).

    Limitations:
      - process_name rules are skipped (need running process context)
      - rule_set rules (geosite-cn) are skipped (need binary file)
      - These fall through to the 'final' outbound (usually sg-auto = proxy)
    """
    if not domain and not ip:
        return {"ok": False, "error": "Provide at least one of domain or ip"}

    config = _load_config()
    if config is None:
        return {"ok": False, "error": f"Cannot read config: {CONFIG_FILE}"}

    result = _simulate_route(config, domain=domain, ip=ip)

    return {
        "ok": True,
        "domain": domain,
        "ip": ip or "(resolved)",
        **result,
    }


if __name__ == "__main__":
    huamcp.run(mcp)
