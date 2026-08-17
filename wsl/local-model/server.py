"""local-model MCP — 将本地轻量 Qwen 模型能力以 FastMCP 协议暴露。

工具:
  local_ask(prompt, model?, system?, json_mode?, think?) — 一次性委托本地 CPU 模型
"""
import json
import os
import pathlib
import sys
import requests

for _p in pathlib.Path(__file__).resolve().parents:
    if (_p / "huamcp.py").exists():
        sys.path.insert(0, str(_p))
        break
import huamcp  # noqa: E402

OLLAMA_URL = os.environ.get("QQ_URL", "http://localhost:11434").rstrip("/")
MODEL_MAP = {
    "4": "qwen3.5:4b-cpu",
    "4b": "qwen3.5:4b-cpu",
    "light": "qwen3.5:4b-cpu",
    "9": "qwen3.5:9b-cpu",
    "9b": "qwen3.5:9b-cpu",
    "big": "qwen3.5:9b-cpu",
}

mcp = huamcp.server(__file__)


@mcp.tool()
def local_ask(
    prompt: str,
    model: str = "4b",
    system: str = "",
    json_mode: bool = False,
    think: bool = False,
) -> str:
    """把无状态轻量任务委托给本地 Qwen 模型 (免费离线运行)。

    【何时用】
    - 分类 / 打标 / 实体抽取 / 数据归一化
    - 快速文本润色 / 代码注释 / 翻译
    - 简单数学或逻辑判定

    【何时别用】
    - 复杂架构设计 / 多文件协同修改 (主模型更强)
    - 极长上下文 (>16k tokens, CPU 推理会变慢)

    【参数】
    - prompt: 任务提示词 (自包含)
    - model: 4b (默认, 快速轻量) 或 9b (推理更好)
    - system: 可选系统提示词
    - json_mode: 是否强制输出合法 JSON
    - think: 是否开启思维链 (默认关闭以保持高吞吐)
    """
    try:
        chosen_model = MODEL_MAP.get(model.strip().lower(), model.strip())
        messages = []
        if system.strip():
            messages.append({"role": "system", "content": system.strip()})
        if json_mode:
            sys_json = "只输出一个合法的 JSON 对象, 不要输出任何其他文字、解释或代码块标记。"
            if messages and messages[0]["role"] == "system":
                messages[0]["content"] += " " + sys_json
            else:
                messages.insert(0, {"role": "system", "content": sys_json})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": chosen_model,
            "messages": messages,
            "stream": False,
            "think": think,
            "keep_alive": "30m",
        }

        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json=payload,
            timeout=600,
        )
        resp.raise_for_status()
        data = resp.json()
        if "error" in data and data["error"]:
            return f"Ollama 错误: {data['error']}"

        return data.get("message", {}).get("content", "(空回复)")
    except Exception as e:  # noqa: BLE001
        return f"工具内部错误: {type(e).__name__}: {e}"


if __name__ == "__main__":
    huamcp.run(mcp)
