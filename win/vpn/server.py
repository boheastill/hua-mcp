"""vpn MCP — manage the network proxy (sing-box) for the agent.

Runs on the Windows host (the proxy is a `sc`-controlled Windows service). Exposes:
  - vpn_restart:   atomic stop → clear cache → start → verify
  - vpn_status:    query proxy groups, selected nodes, service state
  - vpn_logs:      read recent sing-box log lines (optionally filtered by level)
  - vpn_config:    read the current sing-box config.json
  - vpn_config_write: write config.json with JSON validation (does NOT restart)
  - vpn_apply:     write config + restart atomically (the "one-shot" tool)
  - vpn_route_test: simulate rule matching to predict if a domain/IP goes direct or proxy

Design principle: agent manages the network entirely through these tools,
never touching the filesystem or running shell commands directly.
"""
import json
import os
import pathlib
import re
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


# ── helpers ──────────────────────────────────────────────────────────────────

def _service_state() -> str:
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
    try:
        r = requests.get(f"{CLASH_API}{path}", timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def _load_config() -> Optional[dict]:
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
    """Check if an IP is within any CIDR range (simple prefix match)."""
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
    """Simulate sing-box route rule matching. Returns the predicted outbound."""
    rules = config.get("route", {}).get("rules", [])

    # Resolve domain to IP if only domain provided
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

        # ip_is_private
        if rule.get("ip_is_private") and resolved_ip:
            import ipaddress
            try:
                if ipaddress.ip_address(resolved_ip).is_private:
                    return {"outbound": outbound, "rule": "ip_is_private", "matched": True}
            except ValueError:
                pass

        # process_name (can't simulate from domain/IP alone)
        if rule.get("process_name"):
            continue

        # domain_suffix
        if rule.get("domain_suffix") and domain:
            if _domain_matches(domain, rule["domain_suffix"]):
                return {"outbound": outbound, "rule": f"domain_suffix ({len(rule['domain_suffix'])} entries)", "matched": True}

        # ip_cidr
        if rule.get("ip_cidr") and resolved_ip:
            if _ip_in_cidr(resolved_ip, rule["ip_cidr"]):
                return {"outbound": outbound, "rule": f"ip_cidr ({len(rule['ip_cidr'])} ranges)", "matched": True}

        # rule_set (geosite-cn etc.) — can't simulate locally, skip
        if rule.get("rule_set"):
            continue

    # final
    final = config.get("route", {}).get("final", "sg-auto")
    return {"outbound": final, "rule": "final (default)", "matched": True}


# ── tools ────────────────────────────────────────────────────────────────────

@mcp.tool()
def vpn_restart() -> Dict[str, Any]:
    """Atomically restart sing-box and verify it's alive.

    Steps: stop service → wait for TUN release → clear poisoned cache.db →
    start → poll Clash API. Call after config changes or when network is wedged.
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
            f"启动失败。单独跑 'sc start {SERVICE}' 看错误，"
            "或直接 sing-box.exe run -c config.json 看报错。"
        ),
    }


@mcp.tool()
def vpn_status() -> Dict[str, Any]:
    """Query current proxy status: service state, proxy groups, selected nodes."""
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

    Args:
        lines: Number of tail lines (default 30, max 200).
        level: Filter by level, e.g. "ERROR", "WARN". None = all.
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

    Returns the full parsed config. Use this to understand current routing rules,
    outbounds, DNS settings before making changes.
    """
    config = _load_config()
    if config is None:
        return {"ok": False, "error": f"Cannot read config: {CONFIG_FILE}"}

    # Extract summary for quick overview
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

    Args:
        config_json: The full config as a JSON string.
        validate_only: If true, only validate without writing (dry run).

    Returns validation result and, if not dry-run, writes the file.
    Does NOT restart — call vpn_restart or vpn_apply for that.
    """
    # Parse and validate
    try:
        config = json.loads(config_json)
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"Invalid JSON: {e}"}

    # Basic structural validation
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
        return {"ok": True, "valid": True, "note": "dry run — nothing written"}

    # Backup current config
    backup = CONFIG_FILE + ".bak"
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                old = f.read()
            with open(backup, "w", encoding="utf-8") as f:
                f.write(old)
    except OSError:
        pass  # best-effort backup

    # Write new config
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except OSError as e:
        return {"ok": False, "error": f"Write failed: {e}"}

    return {"ok": True, "written": CONFIG_FILE, "backup": backup}


@mcp.tool()
def vpn_apply(config_json: str) -> Dict[str, Any]:
    """Atomically write config + restart + verify. The one-shot "make it so" tool.

    Args:
        config_json: The full config as a JSON string.

    Steps: validate → write config → restart service → verify API.
    Returns combined result of write + restart.
    """
    # Step 1: validate + write
    write_result = vpn_config_write(config_json, validate_only=False)
    if not write_result.get("ok"):
        return {"ok": False, "phase": "write", **write_result}

    # Step 2: restart + verify
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

    Args:
        domain: Domain to test (e.g. "google.com", "live.com").
        ip: IP address to test (e.g. "8.8.8.8"). If only domain is given,
            it will be resolved to an IP via DNS.

    Simulates sing-box's sequential rule matching. Returns the predicted
    outbound and which rule matched. Useful for "would this go direct or proxy?"
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
