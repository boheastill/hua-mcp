"""vpn MCP — manage the network proxy (sing-box) for the agent.

Runs on the Windows host (the proxy is a `sc`-controlled Windows service). Exposes:
  - vpn_restart: atomic stop → clear cache → start → verify
  - vpn_status: query proxy groups, selected nodes, service state
  - vpn_logs: read recent sing-box log lines (optionally filtered by level)

Restart is self-verifying: stop -> wait for TUN release -> clear poisoned cache ->
start -> poll the local Clash API (127.0.0.1, works even when the internet is down).
"""
import os
import pathlib
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
CLASH_API = "http://127.0.0.1:9090"       # local control API used to verify liveness
CACHE_DB = os.path.expanduser("~\\sing-box\\cache.db")  # corrupt cache => start timeout
LOG_FILE = os.path.expanduser("~\\sing-box\\sing-box.log")

mcp = huamcp.server(__file__)


def _service_state() -> str:
    """Return running / stopped / unknown."""
    try:
        r = subprocess.run(
            ["sc", "query", SERVICE], capture_output=True, text=True, timeout=10
        )
        out = r.stdout
        if "RUNNING" in out:
            return "running"
        if "STOPPED" in out:
            return "stopped"
    except Exception:
        pass
    return "unknown"


def _clash_get(path: str, timeout: float = 4) -> Optional[dict]:
    """GET from Clash API; returns None on failure."""
    try:
        r = requests.get(f"{CLASH_API}{path}", timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


# ── tools ────────────────────────────────────────────────────────────────────


@mcp.tool()
def vpn_restart() -> Dict[str, Any]:
    """Atomically restart the VPN/proxy (sing-box Windows service) and verify it's alive.

    Steps: stop service -> wait for TUN release -> delete poisoned cache.db -> start ->
    poll the local Clash API. Call this after editing the proxy config, or when the
    network is wedged. Returns ok=True only once the control API answers.
    """
    steps: List[str] = []

    try:
        stop = subprocess.run(["sc", "stop", SERVICE], capture_output=True, text=True, timeout=20)
        steps.append(f"stop: {(stop.stdout or stop.stderr).strip()[:120]}")
    except Exception as e:
        steps.append(f"stop error: {e}")

    time.sleep(3)  # let the TUN adapter release + process fully exit

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

    time.sleep(3)  # let sing-box finish handshake + TUN init

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
    """Query the current VPN/proxy status: service state, proxy groups, selected nodes.

    Returns service running/stopped, each proxy group's currently selected node,
    and available outbounds. Works even when the internet is down (local API only).
    """
    state = _service_state()
    groups: Dict[str, Any] = {}

    proxies = _clash_get("/proxies")
    if proxies:
        for name, info in proxies.get("proxies", {}).items():
            ptype = info.get("type", "")
            if ptype in ("Selector", "URLTest"):
                now = info.get("now", "?")
                all_opts = info.get("all", [])
                groups[name] = {
                    "type": ptype,
                    "selected": now,
                    "options": all_opts,
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
        lines: Number of tail lines to return (default 30, max 200).
        level: Filter by level (e.g. "ERROR", "WARN"). None = all levels.

    Returns the last N log lines, newest last. Useful for diagnosing why the
    proxy is slow or wedged before calling vpn_restart.
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


if __name__ == "__main__":
    huamcp.run(mcp)
