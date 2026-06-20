"""vpn MCP -- manage the sing-box network proxy on Windows.

Service: "singbox" (Windows service). Config: ~\\sing-box\\config.json.
Clash API: 127.0.0.1:9090. Architecture docs: D:\\vpn-configs\\architecture.md

Servers:
  SG 47.130.65.208 (admin) -- Hy2 UDP 443 + SS2022 TCP 8443
  US 66.154.101.110 (root) -- SS2022 TCP 8443
  Azure 52.146.92.1 (bohea) -- WireGuard UDP 51820
  SSH: ssh -i D:/ssh-keys/lbqg.pem <user>@<ip>

Groups: sg-auto (URLTest: hy2-sg/ss-sg), agent-group (Selector: agent-sg/agent-us)

Fallback (when all proxy nodes unreachable):
  Azure WireGuard: D:\\ssh-keys\\azure-au-wg.conf (connect in WireGuard client)
  US OpenVPN: D:\\vpn-configs\\us-openvpn-tcp.ovpn (OpenVPN, TCP 443)
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
    """Restart sing-box service and verify it's alive.

    Returns: ok (bool), steps (list), hint (str if failed).
    If ok=False twice, switch nodes instead of retrying.
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
    """Query service state and proxy group selections.

    Returns: service ("running"/"stopped"), groups dict with selected node per group.
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
    """Test API, proxy (google.com), and direct (baidu.com) connectivity.

    Returns: api_ok, proxy_ok, direct_ok (bool each), diagnosis (str).
    Call this FIRST when network goes down.
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

    Args: lines (1-200, default 30), level filter ("ERROR", "WARN", etc).
    Returns: ok, total_in_file, returned, lines (list[str]).
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
    """Read current sing-box config.json.

    Returns: ok, path, summary (route_rules count, outbounds list, dns_servers, final_outbound), config (full dict).
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
    """Write config.json with JSON + structural validation. Does NOT restart.

    Args: config_json (full config string), validate_only (dry run if true).
    Returns: ok, written path, backup path, or errors list.
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
    """Write config + restart + verify. One-shot.

    Args: config_json (full config string).
    Returns: ok, write result, restart result.
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
    """Switch proxy group to a different outbound via Clash API. Temporary (lost on restart).

    Args: target -- "ss-sg", "hy2-sg", "sg-auto", "agent-us", "agent-sg".
    Returns: ok, target, group, note.
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
    """Predict which outbound a domain/IP would use (simulates rule matching).

    Args: domain (e.g. "google.com") and/or ip (e.g. "8.8.8.8").
    Returns: ok, domain, ip, outbound, rule, matched.
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
