"""vpn — restart the network proxy (sing-box) for the agent.

The live proxy runs as a **Windows service** (`sc`-controlled) on the Windows host,
so this lives in win_agents. We deliberately expose ONLY a restart: switching nodes /
speed tests / SSH probes were dropped — the agent just needs to bring the link back
when it wedges (e.g. after a config edit, or a stuck TUN adapter).

Restart is atomic and self-verifying: stop → wait for TUN release → clear a poisoned
cache → start → poll the local Clash API to confirm it's actually alive (works even
while the internet is down, since the API is on 127.0.0.1).
"""
import os
import subprocess
import time
from typing import Any, Dict, List

import requests

SERVICE = "singbox"                       # Windows service name (sc stop/start)
CLASH_API = "http://127.0.0.1:9090"       # local control API used to verify liveness
CACHE_DB = os.path.expanduser("~\\sing-box\\cache.db")  # corrupt cache => start timeout


def vpn_restart() -> Dict[str, Any]:
    """Atomically restart the VPN/proxy (sing-box Windows service) and verify it's alive.

    Steps: stop service → wait for TUN release → delete poisoned cache.db → start →
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


def register(mcp):
    mcp.tool()(vpn_restart)
