"""zcode-bridge MCP — 把本机 zcode agent 当编码执行器（1.5x 额度通道）。

上游链路: 本工具 → HTTP 127.0.0.1:9230 (bridge-api) → CDP 9222 → 真 zcode 实例。
zcode 是任务型 agent: 提交一段任务描述, 它自己读文件/跑命令/改代码后交付。
产出文件落在本机磁盘(zcode 工作区), 用普通文件工具读取。

服务依赖(不在本工具内, 由 systemd 管):
  systemctl --user status zcode-bridge zcode-bridge-api
手册: ~/bh-workspace/agent/zcode/quota-multiplier-research/bridge/bridge-usage.md
"""
import json
import pathlib
import sys
import time
import urllib.request
from typing import Any, Dict, Optional

for _p in pathlib.Path(__file__).resolve().parents:
    if (_p / "huamcp.py").exists():
        sys.path.insert(0, str(_p))
        break
import huamcp  # noqa: E402

mcp = huamcp.server(__file__)

BRIDGE = "http://127.0.0.1:9230"


def _http(method: str, path: str, body: Optional[Dict] = None, timeout: int = 60) -> Dict[str, Any]:
    req = urllib.request.Request(
        BRIDGE + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


@mcp.tool()
def zcode_task(prompt: str, wait_seconds: int = 300) -> Dict[str, Any]:
    """把一个重编码任务委托给本机 zcode agent 执行（全功能编码 agent，OAuth 1.5x 额度通道），阻塞等完成并返回结果尾部。

    为什么值得派（经济学）：
    - 额度账：zcode 走 OAuth 签名通道，同等调用量只扣 67% 积分（1.5x 活动）；你自己调 API 是 1x 扣订阅额度。重活派出去 = 省将近一半额度。
    - 上下文账：任务的全部中间过程（读文件/跑命令/试错）都在 zcode 里消耗，不占你的上下文窗口；你只收最终结果尾部。长任务这对你是真金白银。
    - 能力账：它是全功能 agent（自主规划/子智能体/直接操作本机文件系统），重活自己会拆解执行到交付。

    何时派：预期 >5 分钟或涉及 >10 文件的整活——重构、批量文件操作、深度代码审查、生成整个项目/模块、修复杂 bug。像 bash 一样一次调用，无需分派仪式。

    何时别派（自己做更快）：单文件小改/读文件/查状态（文件工具更快）；需要逐步人审的精修；纯问答分析。

    并发安全：底层有任务队列，**可以连续派多个**（自动排队串行执行），每个任务的输出独立追踪互不串扰（按任务在 zcode 数据库中定位，不依赖 UI 视图）。
    wait_seconds 到点未完成则返回当前进度（任务继续跑，之后用 zcode_status 查）。

    prompt 写成给编码助手的完整任务描述（目标/路径/验收标准）。产出文件落本机磁盘，用你的文件工具读取验证。"""
    t0 = time.time()
    try:
        sub = _http("POST", "/task", {"prompt": prompt})
    except Exception as e:
        return {"ok": False, "stage": "bridge-unreachable", "hint": "check systemctl --user status zcode-bridge zcode-bridge-api", "error": str(e)}
    if not sub.get("ok"):
        return {"ok": False, "stage": "submit", "detail": sub}
    tid = sub.get("taskId")
    deadline = time.time() + max(30, wait_seconds)
    last = None
    while time.time() < deadline:
        time.sleep(6)
        try:
            last = _http("GET", "/task?id=" + str(tid), timeout=15)
        except Exception as e:
            last = {"state": "poll-error", "error": str(e)}
            continue
        st = last.get("state")
        if st in ("done", "failed", "stalled"):
            return {"ok": st == "done", "taskId": tid, "state": st,
                    "elapsed_s": round(time.time() - t0),
                    "title": last.get("title"), "error": last.get("error"),
                    "output": (last.get("output") or "")[-3000:]}
    return {"ok": True, "taskId": tid, "state": "timeout",
            "hint": "task still queued/running; zcode_status to monitor",
            "elapsed_s": round(time.time() - t0),
            "output": ((last or {}).get("output") or "")[-2000:]}


@mcp.tool()
def zcode_status() -> Dict[str, Any]:
    """深度健康检查：zcode 桥全链状态（CDP 连通/输入区/模型可用/队列长度/当前任务列表）+ 最近任务列表。排障第一步。"""
    out = {}
    try:
        out["health"] = _http("GET", "/health", timeout=15)
    except Exception as e:
        return {"ok": False, "error": str(e), "hint": "bridge-api unreachable: systemctl --user status zcode-bridge-api"}
    try:
        out["recent_tasks"] = _http("GET", "/tasks", timeout=15)[-10:]
    except Exception:
        pass
    return out


if __name__ == "__main__":
    huamcp.run(mcp)
