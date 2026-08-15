"""Antigravity agent MCP — 把终端里的全模态 agent (agy) 暴露为 MCP 工具。

工具:
  agy_ask(prompt, paths?, model?, effort?, conversation?) — 一次性 print 模式委托
  agy_quota() — 查模型额度剩余 (驱动 TUI 的 /usage 面板, PTY 抓取)
agy 的登录态/配置由它自己在 ~/.gemini 等位置管理, 本服务不碰。

注意: 每个工具的整个函数体都必须被 try/except 兜底——
未处理异常会让 FastMCP 清理该 streamable-http 会话,
客户端随后所有调用都会报 Session not found (-32600)。
"""
import pathlib
import sys

for _p in pathlib.Path(__file__).resolve().parents:
    if (_p / "huamcp.py").exists():
        sys.path.insert(0, str(_p))
        break
import huamcp  # noqa: E402

import fcntl
import json
import os
import pty
import re
import select
import signal
import struct
import subprocess
import termios
import time
from typing import List, Optional

AGY = "/home/bohea/.local/bin/agy"
CALL_TIMEOUT_S = 270

mcp = huamcp.server(__file__)


@mcp.tool()
def agy_ask(
    prompt: str,
    paths: Optional[List[str]] = None,
    model: str = "gemini-3.7-flash-high",
    effort: str = "high",
    conversation: str = "",
) -> str:
    """调用终端里的 Antigravity agent (agy, 全模态) 执行一次性任务。

【用途】把复杂/多模态/需联网的独立任务整包委托给 agy: 它会自己读文件、
看图、上网、跑工具、内部循环, 最后只把结论带回来。适合 DeepSeek 主代理
"外包重活"。纯看图且要便宜请用 glmvision 的 describe_image(秒级、不留会话)。

【参数】
- prompt: 任务描述。要引用文件时写绝对路径, 并把路径也放进 paths。
- paths: 需要开放给 agy 读的文件/目录列表(会加入它的工作区)。
- model: 默认 gemini-3.7-flash-high(强推理)。可换 claude-opus-4-6-thinking、
  gemini-3.1-pro-high 等(`agy models` 是完整列表)。
- effort: 推理档 low|medium|high, 默认 high(最高)。
- conversation: 上次 agy_ask 返回的 conversation_id。传入即可在同一会话
  续聊(多轮协作、追问、带着上次上下文继续), 留空=新开会话。

【返回】结论文本 + conversation_id + 本次 token 用量。
【代价】每次调用数秒到数分钟; 在 agy 本地留一条会话记录; 按 agy 账户计费。
"""
    try:
        args = [
            AGY, "-p", prompt,
            "--dangerously-skip-permissions",
            "--output-format", "json",
            "--print-timeout", "4m",
        ]
        if model.strip():
            args += ["--model", model.strip()]
        if effort.strip():
            args += ["--effort", effort.strip()]
        if conversation.strip():
            args += ["--conversation", conversation.strip()]
        for raw in paths or []:
            if not isinstance(raw, str) or not raw:
                continue
            d = pathlib.Path(raw).expanduser()
            args += ["--add-dir", str(d.parent if d.is_file() else d)]
        for attempt in (1, 2):
            try:
                r = subprocess.run(
                    args, capture_output=True, text=True, timeout=CALL_TIMEOUT_S,
                    cwd=str(pathlib.Path.home()),
                )
            except subprocess.TimeoutExpired:
                return f"agy 超时 ({CALL_TIMEOUT_S}s)"
            if r.returncode == 0:
                break
            if attempt == 1:
                time.sleep(2)  # 瞬时失败(如并发的 agy 实例锁)重试一次
        if r.returncode != 0:
            return f"agy 失败 (exit {r.returncode}): {r.stderr.strip()[-400:]}"
        out = r.stdout.strip()
        try:
            j = json.loads(out.splitlines()[-1])
        except (ValueError, IndexError):
            return out[-8000:] or "(空输出)"
        if j.get("status") and j["status"] != "SUCCESS":
            return f"agy 状态 {j['status']}: {str(j.get('error', ''))[:400]}"
        resp = j.get("response") or "(空回复)"
        cid = j.get("conversation_id") or ""
        if cid:
            resp += f"\n\n[会话ID] {cid} (续聊时把它传给 conversation 参数)"
        usage = j.get("usage") or {}
        if usage:
            resp += (
                f"\n[本次用量] 输入 {usage.get('input_tokens', '?')} / "
                f"输出 {usage.get('output_tokens', '?')} / "
                f"思考 {usage.get('thinking_tokens', '?')} tokens"
            )
        return resp
    except Exception as e:  # noqa: BLE001 — 绝不让异常杀死 MCP 会话
        return f"工具内部错误: {type(e).__name__}: {e}"


def _capture_usage_panel(timeout_s: int = 60) -> str:
    """在伪终端里驱动 `agy usage`, 自动确认信任、发送 /usage, 抓取额度面板。"""
    pid, fd = pty.fork()
    if pid == 0:
        os.environ["TERM"] = "xterm-256color"
        os.chdir(str(pathlib.Path.home()))
        os.execv(AGY, ["agy", "usage"])
    out = b""
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 45, 130, 0, 0))
        sent_trust = sent_cmd = False
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            r, _, _ = select.select([fd], [], [], 0.5)
            if not r:
                continue
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
            if not sent_trust and b"trust the contents" in out:
                time.sleep(1.2)
                os.write(fd, b"\r")
                sent_trust = True
            if not sent_cmd and b"for shortcuts" in out:
                time.sleep(1.5)
                os.write(fd, b"/usage\r")
                sent_cmd = True
            if b"emaining" in out:
                time.sleep(2)
                break
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass
    text = out.decode("utf-8", "ignore")
    return re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b[>=]|\x1b[()][0-9A-B]", "", text)


@mcp.tool()
def agy_quota() -> str:
    """查询 agy (Antigravity) 的模型额度剩余。

返回各模型组(Gemini / Claude+GPT)的周额度和 5 小时额度的剩余百分比与重置时间。
每次调用约 10~30 秒(需要拉起 agy TUI 抓取 /usage 面板)。
"""
    try:
        text = _capture_usage_panel()
        keep: List[str] = []
        for line in text.splitlines():
            s = re.sub(r"[ \t]+", " ", line).strip()
            if not s:
                continue
            if re.search(
                r"Account:|MODELS$|Weekly Limit Remaining|Five Hour Limit Remaining|remaining · Refreshes",
                s,
            ):
                keep.append(s)
        if not keep:
            return "未能解析额度面板(可能未登录或网络问题)。原始输出尾部:\n" + text[-400:]
        return "agy 额度剩余:\n" + "\n".join(keep)
    except Exception as e:  # noqa: BLE001 — 绝不让异常杀死 MCP 会话
        return f"工具内部错误: {type(e).__name__}: {e}"


if __name__ == "__main__":
    huamcp.run(mcp)
