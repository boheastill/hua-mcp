"""vpn MCP — restart the network proxy (sing-box) for the agent.

Runs on the Windows host (the proxy is a `sc`-controlled Windows service). Exposes
ONLY a restart: switching nodes / speed tests / SSH probes were intentionally dropped
— the agent just needs to bring the link back when it wedges.

Restart is atomic and self-verifying: stop -> wait for TUN release -> clear a poisoned
cache -> start -> poll the local Clash API (127.0.0.1, works even when the internet
is down). Self-contained: reads its own mcp.json for name+port.
"""
import json
import os
import pathlib
import subprocess
import sys
import time
from typing import Any, Dict, List

import requests
from mcp.server.fastmcp import FastMCP

HERE = pathlib.Path(__file__).resolve().parent
META = json.loads((HERE / "mcp.json").read_text(encoding="utf-8"))

SERVICE = "singbox"                       # Windows service name (sc stop/start)
CLASH_API = "http://127.0.0.1:9090"       # local control API used to verify liveness
CACHE_DB = os.path.expanduser("~\\sing-box\\cache.db")  # corrupt cache => start timeout

mcp = FastMCP(META["name"], host="0.0.0.0", port=META["port"])


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


@mcp.custom_route("/health", methods=["GET"])
async def _health(request):
    from starlette.responses import JSONResponse

    return JSONResponse({"ok": True, "mcp": META["name"], "os": META["os"], "port": META["port"]})


if __name__ == "__main__":
    mcp.run() if "--stdio" in sys.argv else mcp.run(transport="streamable-http")
