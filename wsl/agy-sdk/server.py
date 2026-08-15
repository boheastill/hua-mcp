"""Antigravity agent MCP — 官方 Python SDK (google-antigravity) 版。

工具:
  agy_sdk_ask(prompt, paths?, model?, effort?, conversation?) — SDK 委托
  agy_quota() — 查模型额度剩余 (PTY 驱动 CLI 的 /usage, 与 agy 成员同款)

【设计意图】(用户定稿): 保留 CLI 版成员 wsl/agy (8103, 订阅额度, 稳定),
本成员是 SDK 版 (8105), 工具描述里写清"建议优先 SDK, 不通就走 agy"。

【当前状态 2026-08-15】SDK 的 localharness 强制以 x-goog-api-key 发 key,
而 Code Assist 订阅端点只认 Bearer OAuth → SDK Agent 会话初始化即失败。
故本工具实际是"尝试 SDK → 失败时返回指引, 让调用方回退 mcp__agy__agy_ask"。
等官方 SDK 支持 Bearer/复用 CLI 登录态后, 此成员自动点亮, 无需改客户端。
注意: 工具体必须 try/except 兜底, 未处理异常会让 FastMCP 清理会话。
"""
import pathlib
import sys

for _p in pathlib.Path(__file__).resolve().parents:
    if (_p / "huamcp.py").exists():
        sys.path.insert(0, str(_p))
        break
import huamcp  # noqa: E402

import asyncio
import fcntl
import json
import os
import pty
import re
import select
import signal
import struct
import termios
import time
from typing import List, Optional

from google.antigravity import Agent, LocalAgentConfig, types
from google.antigravity.hooks.policy import allow_all
from google.antigravity.models import GeminiAPIEndpoint, ModelTarget

AGY_BIN = "/home/bohea/.local/bin/agy"
TOKEN_FILE = pathlib.Path.home() / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
AICODE_HOST = "https://aicode.googleapis.com"
CALL_TIMEOUT_S = 180
DEFAULT_MODEL = "gemini-3.7-flash-high"
FALLBACK_HINT = "请改用 mcp__agy__agy_ask(CLI 订阅版) 完成该任务"

mcp = huamcp.server(__file__)


def _access_token() -> str:
    """读取 agy CLI 的 OAuth access_token (Bearer)。"""
    try:
        d = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        return (d.get("token") or {}).get("access_token") or ""
    except (OSError, ValueError):
        return ""


def _effort_model(model: str, effort: str) -> str:
    m = model.strip() or DEFAULT_MODEL
    e = effort.strip().lower()
    if e in ("low", "medium", "high"):
        base = re.sub(r"-(low|medium|high)$", "", m)
        return {"low": base + "-low", "high": base + "-high"}.get(e, base + "-medium")
    return m


@mcp.tool()
def agy_sdk_ask(
    prompt: str,
    paths: Optional[List[str]] = None,
    model: str = DEFAULT_MODEL,
    effort: str = "high",
    conversation: str = "",
) -> str:
    """【建议优先】用 Antigravity 官方 SDK 委托全模态 agent (同款 agy 账户/额度)。

与 CLI 版 mcp__agy__agy_ask 等价能力(读文件/看图/联网/内部循环), 走进程内
SDK 通道。**若本工具报"SDK 通道不可用/401/连接重置", 请直接回退用
mcp__agy__agy_ask**(CLI 订阅版, 稳定)。

【参数】prompt 任务描述(引用文件写绝对路径并列入 paths); paths 开放给 agent
读的文件/目录(省略默认整个家目录); model 默认 gemini-3.7-flash-high;
effort low|medium|high 默认 high; conversation 传上次返回的会话ID续聊。
【代价】数秒到数分钟; 本地留一条会话记录; 按 agy 账户额度计费。
"""
    try:
        tok = _access_token()
        if not tok:
            return f"未找到 agy 登录态({TOKEN_FILE})。{FALLBACK_HINT}"
        workspaces = [str(pathlib.Path(p).expanduser()) for p in (paths or [])]
        if not workspaces:
            workspaces = [str(pathlib.Path.home())]

        async def run():
            # localharness 强制 api_key 非空; 端点实际只认 Bearer OAuth。
            endpoint = GeminiAPIEndpoint(
                base_url=AICODE_HOST,
                api_key=tok,  # 占位满足校验, 真实鉴权走下面的 Authorization 头
                http_headers={"Authorization": f"Bearer {tok}"},
            )
            target = ModelTarget(
                name=_effort_model(model, effort),
                types=list(types.ModelType),
                endpoint=endpoint,
            )
            config = LocalAgentConfig(
                models=[target],
                policies=[allow_all()],
                workspaces=workspaces,
                conversation_id=conversation.strip() or None,
            )
            async with Agent(config) as agent:
                resp = await asyncio.wait_for(agent.chat(prompt), CALL_TIMEOUT_S)
                text = await asyncio.wait_for(resp.text(), CALL_TIMEOUT_S)
                return text or "(空回复)", agent.conversation_id

        text, cid = asyncio.run(run())
        if cid:
            text += f"\n\n[会话ID] {cid} (续聊时把它传给 conversation 参数)"
        return text
    except asyncio.TimeoutError:
        return f"SDK 超时 ({CALL_TIMEOUT_S}s)。{FALLBACK_HINT}"
    except Exception as e:  # noqa: BLE001 — 绝不让异常杀死 MCP 会话
        msg = str(e).replace(_access_token(), "***")[:240]
        return f"SDK 通道不可用 ({type(e).__name__}: {msg})。{FALLBACK_HINT}"


def _capture_usage_panel(timeout_s: int = 60) -> str:
    """在伪终端里驱动 `agy usage`, 自动确认信任、发送 /usage, 抓取额度面板。"""
    pid, fd = pty.fork()
    if pid == 0:
        os.environ["TERM"] = "xterm-256color"
        os.chdir(str(pathlib.Path.home()))
        os.execv(AGY_BIN, ["agy", "usage"])
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
    """查询 agy (Antigravity) 的模型额度剩余 (Gemini / Claude+GPT 周额度和 5 小时额度)。"""
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
    except Exception as e:  # noqa: BLE001
        return f"工具内部错误: {type(e).__name__}: {e}"


if __name__ == "__main__":
    huamcp.run(mcp)
