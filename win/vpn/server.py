"""vpn MCP -- manage the network proxy (sing-box) for the agent.

WHAT THIS MCP DOES:
  Provides a safe interface for agents to manage the Windows network proxy
  (sing-box) without touching the filesystem or running shell commands.

WHAT IS SING-BOX:
  sing-box is a universal proxy platform running as a Windows service ("singbox").
  It intercepts all traffic via a TUN adapter (172.19.0.1) and routes it based on
  rules: direct for domestic/whitelisted sites, proxy (via Singapore VPS) for
  everything else. The Clash-compatible API at 127.0.0.1:9090 exposes status.

CONFIG FILE:
  C:\\Users\\bohea\\sing-box\\config.json -- the sing-box routing/outbound/DNS config.
  Architecture documentation: D:\\vpn-configs\\architecture.md

TOOLS (in typical workflow order):
  1. vpn_status      -- see current state (which node, service running?)
  2. vpn_logs        -- check recent errors before making changes
  3. vpn_config      -- read the current config to understand rules
  4. vpn_route_test  -- predict if a domain goes direct or proxy
  5. vpn_config_write -- modify config (with validation, does NOT restart)
  6. vpn_apply       -- write config + restart + verify (one-shot)
  7. vpn_restart     -- just restart without config change (e.g. after network wedge)

TYPICAL WORKFLOW:
  # Agent wants to add "example.com" to the proxy list:
  1. cfg = vpn_config()                          # read current config
  2. vpn_route_test(domain="example.com")        # confirm it currently goes direct
  3. Modify the config dict: add "example.com" to the proxy domain_suffix list
  4. vpn_apply(config_json=json.dumps(cfg))      # write + restart + verify
  5. vpn_route_test(domain="example.com")        # confirm it now goes to sg-auto

  # Agent suspects network is broken:
  1. vpn_status()                                # is the service running?
  2. vpn_logs(level="ERROR", lines=20)           # what errors are happening?
  3. vpn_restart()                               # try restarting
  4. vpn_status()                                # verify recovery

DESIGN PRINCIPLE:
  Agent manages the network entirely through these tools, never touching the
  filesystem or running shell commands directly. Every write is validated and
  backed up. Every restart is self-verifying.
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

SERVICE = "singbox"                       # Windows service name (sc stop/start)
CLASH_API = "http://127.0.0.1:9090"       # sing-box Clash-compatible control API
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

    Note: process_name rules cannot be simulated (need running process context).
    rule_set rules (geosite-cn) are skipped (need the binary rule file).
    These will fall through to the 'final' outbound.
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
            continue  # system rules (sniff, hijack-dns, reject)

        if rule.get("ip_is_private") and resolved_ip:
            import ipaddress
            try:
                if ipaddress.ip_address(resolved_ip).is_private:
                    return {"outbound": outbound, "rule": "ip_is_private", "matched": True}
            except ValueError:
                pass

        if rule.get("process_name"):
            continue  # can't simulate

        if rule.get("domain_suffix") and domain:
            if _domain_matches(domain, rule["domain_suffix"]):
                return {"outbound": outbound, "rule": f"domain_suffix ({len(rule['domain_suffix'])} entries)", "matched": True}

        if rule.get("ip_cidr") and resolved_ip:
            if _ip_in_cidr(resolved_ip, rule["ip_cidr"]):
                return {"outbound": outbound, "rule": f"ip_cidr ({len(rule['ip_cidr'])} ranges)", "matched": True}

        if rule.get("rule_set"):
            continue  # can't simulate locally

    final = config.get("route", {}).get("final", "sg-auto")
    return {"outbound": final, "rule": "final (default)", "matched": True}


# -- tools --------------------------------------------------------------------

@mcp.tool()
def vpn_restart() -> Dict[str, Any]:
    """Atomically restart sing-box and verify it's alive.

    Steps: stop service -> wait 3s for TUN release -> delete poisoned cache.db ->
    start service -> poll Clash API up to 5 times.

    When to call:
      - After editing config.json manually (not via vpn_config_write)
      - When the network is wedged (no connectivity, API unreachable)
      - As a last resort before investigating deeper

    Returns:
      ok (bool): True if Clash API answered within 15s.
      sc_start_ok (bool): Whether sc start returned success.
      steps (list[str]): Human-readable log of what happened.
      hint (str|None): Error guidance if ok=False.
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
            "If still broken, check vpn_logs(level='ERROR') for root cause."
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
      - "dial tcp ... actively refused it" = remote port not listening
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
