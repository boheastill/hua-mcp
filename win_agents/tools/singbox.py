"""singbox — sing-box / Clash proxy control (migrated from mcp-servers/singbox).

Lives in win_agents because it must run on the Windows host: it talks to the local
Clash API (127.0.0.1:9090), restarts the sing-box **Windows service**, and uses an
SSH key on the C: drive. WSL agents reach these tools over the fleet port (:8001).
"""
import subprocess
from typing import Any, Dict

import requests

API = "http://127.0.0.1:9090"
# Cloudflare endpoint for latency (Google/gstatic mis-measures US routes).
TEST_URL = "http://cp.cloudflare.com/generate_204"
NODES = ["hy2-sg", "ss-sg", "vmess-sg", "agent-aws", "us-mux"]
GROUPS = ["agent-group", "sg-auto"]
SSH_KEY = "C:/base-info/key/lbqg.pem"
US_HOST = "root@66.154.101.110"


def _delay(node: str, timeout_ms: int = 5000) -> Any:
    """Measure one node's latency; returns ms or -1 (unreachable)."""
    try:
        r = requests.get(
            f"{API}/proxies/{requests.utils.quote(node, safe='')}/delay",
            params={"timeout": timeout_ms, "url": TEST_URL},
            timeout=(timeout_ms / 1000) + 3,
        )
        if r.status_code == 200:
            return r.json().get("delay", -1)
        return -1
    except Exception:
        return -1


def singbox_status() -> Dict[str, Any]:
    """sing-box running state + which node each group (agent-group/sg-auto) currently uses."""
    out: Dict[str, Any] = {"running": False, "groups": {}, "error": None}
    try:
        v = requests.get(f"{API}/version", timeout=4)
        out["running"] = v.status_code == 200
        out["version"] = v.json().get("version") if v.status_code == 200 else None
    except Exception as e:
        out["error"] = f"Clash API 不可达，sing-box 可能没运行: {e}"
        return out
    for g in GROUPS:
        try:
            r = requests.get(f"{API}/proxies/{g}", timeout=4)
            if r.status_code == 200:
                j = r.json()
                out["groups"][g] = {"now": j.get("now"), "all": j.get("all", [])}
        except Exception:
            pass
    return out


def singbox_test_all() -> Dict[str, Any]:
    """Latency of all nodes via Cloudflare (ms; -1 = dead). Helps pick the fastest line."""
    results = {n: _delay(n) for n in NODES}
    ranked = sorted([(n, d) for n, d in results.items() if d >= 0], key=lambda x: x[1])
    return {
        "delays_ms": results,
        "ranked_fastest_first": ranked,
        "dead_nodes": [n for n, d in results.items() if d < 0],
        "note": "延迟含 中国→节点 全程往返；-1 表示该节点当前不通",
    }


def singbox_switch(group: str, node: str) -> Dict[str, Any]:
    """Switch a group's active node via Clash API (live, no restart).

    Args:
        group: "agent-group" (agent egress) or "sg-auto".
        node: target node. agent-group: agent-aws/us-mux/sg-auto; sg-auto: hy2-sg/ss-sg/vmess-sg.
    """
    try:
        r = requests.put(
            f"{API}/proxies/{requests.utils.quote(group, safe='')}",
            json={"name": node},
            timeout=5,
        )
        if r.status_code in (200, 204):
            cur = requests.get(f"{API}/proxies/{group}", timeout=4).json().get("now")
            return {"ok": True, "group": group, "now": cur}
        return {"ok": False, "status": r.status_code, "body": r.text}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def singbox_speedtest_us() -> Dict[str, Any]:
    """SSH into the US server and run speedtest (bypassing CN broadband + proxy), then
    compare with local-via-proxy latency — answers "slow machine or slow link?"."""
    out: Dict[str, Any] = {}
    try:
        cmd = [
            "ssh", "-i", SSH_KEY,
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=15",
            US_HOST, "speedtest-cli --simple 2>/dev/null || echo NO_SPEEDTEST",
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        out["us_native_speedtest"] = r.stdout.strip() or r.stderr.strip()
    except Exception as e:
        out["us_native_speedtest"] = f"失败: {e}"
    out["us_mux_delay_via_proxy_ms"] = _delay("us-mux")
    out["interpretation"] = (
        "us_native 是 US 服务器到公网的上限(预期~600Mbit)；"
        "us_mux_delay 是你家→US 经代理的往返。前者好后者差=国际段卡，非服务器问题。"
    )
    return out


def singbox_restart() -> Dict[str, Any]:
    """Restart the sing-box Windows service (sc stop/start). Use after editing config.json."""
    try:
        subprocess.run(["sc", "stop", "singbox"], capture_output=True, text=True, timeout=20)
        start = subprocess.run(["sc", "start", "singbox"], capture_output=True, text=True, timeout=20)
        ok = "START_PENDING" in start.stdout or "RUNNING" in start.stdout or start.returncode == 0
        return {
            "ok": ok,
            "stdout": start.stdout.strip()[-300:],
            "hint": None if ok else "若失败：服务未安装(跑 install-service.bat)或无权限",
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "hint": "可能 sing-box 还没做成服务"}


def register(mcp):
    for fn in (
        singbox_status,
        singbox_test_all,
        singbox_switch,
        singbox_speedtest_us,
        singbox_restart,
    ):
        mcp.tool()(fn)
