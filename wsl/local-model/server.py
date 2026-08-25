"""local-model MCP v2 — 本地大模型(llama-server, 真身在 lb 台式机)的 MCP 门面。

2026-08-25 v2 重写:
  - 旧版打本机 ollama(11434, 已死); 现指向 lb 的 llama-server(OpenAI 兼容)。
  - lb 单卡互斥, 同时只跑一个模型(set); 本 MCP 启动/缓存期自动发现
    /v1/models 里的活模型, 换模型(stop 旧 + start 新)无需改这里。
  - 模型资产单一事实源: ~/bh-workspace/docs/model-registry/README.md
  - 新增 local_vision 工具(qwen3.8-27b 多模态实测可用)。

工具:
  local_ask(prompt, model?, system?, json_mode?)   — 文本委托(自动选活模型)
  local_vision(image_path, question?, model?)      — 本地看图(多模态模型)
"""
import os
import pathlib
import sys
import time
import requests

for _p in pathlib.Path(__file__).resolve().parents:
    if (_p / "huamcp.py").exists():
        sys.path.insert(0, str(_p))
        break
import huamcp  # noqa: E402

LLM_BASE = os.environ.get("LB_LLM_URL", "http://192.168.31.71:8080/v1").rstrip("/")
REGISTRY_HINT = "模型台账: ~/bh-workspace/docs/model-registry/README.md (lb 上 systemctl --user start llama-server@<set>)"

_cache = {"ts": 0.0, "models": []}
_CACHE_TTL = 60.0


def env_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
        return value if value >= 0 else default
    except ValueError:
        return default


def _list_models(force: bool = False) -> list:
    now = time.time()
    if not force and _cache["models"] and now - _cache["ts"] < _CACHE_TTL:
        return _cache["models"]
    try:
        resp = requests.get(f"{LLM_BASE}/models", timeout=10)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise RuntimeError(
            f"lb llama-server 不可达 ({LLM_BASE}): {type(e).__name__}。"
            f"先确认 lb 在线且 llama-server 已起; {REGISTRY_HINT}"
        ) from e
    data = resp.json().get("data", [])
    ids = [m.get("id", "") for m in data if m.get("id")]
    _cache["models"] = ids
    _cache["ts"] = now
    return ids


def _resolve_model(model: str) -> str:
    """解析调用方给的 model 参数到 llama-server 模型 id。

    - ""/"auto" → 自动取活模型(第一个; 单卡互斥, lb 上换模型免改这里)
    - 含 "/" 且命中活列表 → 原样使用(完整 gguf 路径 id)
    - 短名(如 qwen3.8-27b / 27b) → 模糊匹配活列表(id 路径中含该串)
    """
    live = _list_models()
    if not live:
        raise RuntimeError(f"{LLM_BASE} 在线但无在跑模型; {REGISTRY_HINT}")
    key = (model or "").strip()
    if not key or key == "auto":
        return live[0]
    if key in live:
        return key
    for mid in live:
        if key in mid:
            return mid
    raise RuntimeError(f"模型 {model!r} 不在活列表 {live}; 见 model-registry 台账")


def _chat(model_id: str, messages: list, max_tokens: int, temperature: float) -> str:
    payload = {
        "model": model_id,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    resp = requests.post(f"{LLM_BASE}/chat/completions", json=payload, timeout=600)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data and data["error"]:
        return f"llama-server 错误: {data['error']}"
    return data.get("choices", [{}])[0].get("message", {}).get("content", "(空回复)")


mcp = huamcp.server(__file__)


@mcp.tool()
def local_ask(prompt: str, model: str = "", system: str = "", json_mode: bool = False) -> str:
    """把无状态轻量任务委托给本地大模型 (lb 台式机 llama-server, 免费离线)。

    【何时用】
    - 分类 / 打标 / 实体抽取 / 数据归一化
    - 快速文本润色 / 代码注释 / 翻译
    - 简单数学或逻辑判定 (复杂推理仍走主模型)

    【参数】
    - prompt: 任务提示词 (自包含)
    - model: 留空=自动用 lb 当前在跑的模型 (推荐, 单卡互斥换模型免改配置);
             也可给短名如 qwen3.8-27b / 27b (对活模型 id 模糊匹配)
    - system: 可选系统提示词
    - json_mode: 是否强制输出合法 JSON
    """
    try:
        model_id = _resolve_model(model)
        sys_content = system.strip() or "你是用户的本地私有模型, 直接给出有用、完整的回答。"
        if json_mode:
            sys_content += " 只输出一个合法的 JSON 对象, 不要输出任何其他文字、解释或代码块标记。"
        messages = [{"role": "system", "content": sys_content},
                    {"role": "user", "content": prompt}]
        return _chat(model_id, messages,
                     max_tokens=env_int("LOCAL_MAX_TOKENS", 1024),
                     temperature=float(os.environ.get("LOCAL_TEMP", "0.7")))
    except Exception as e:  # noqa: BLE001
        return f"工具内部错误: {type(e).__name__}: {e}"


@mcp.tool()
def describe_image(path: str, question: str = "详细描述这张图片的内容", model: str = "") -> str:
    """看图回答问题 — 与云端 glmvision 的 describe_image 同名同参(兼容 phone-eye 等调用方)。

    【何时用】与 local_vision 完全相同; 存在这个别名是为了让"视觉端点可插拔"的
    调用方(phone-eye 的 PHONE_EYE_VISION_URL)零改动切到本地离线视觉。
    参数名对齐: path/question(而非 image_path)。
    """
    return local_vision(path, question, model)


@mcp.tool()
def local_vision(image_path: str, question: str = "详细描述这张图片的内容", model: str = "") -> str:
    """用本地多模态模型看图 (免费离线, 数据不出局域网)。

    【何时用】
    - 手机截图 / UI 自动化判读 (adb 截图闭环)
    - 隐私敏感图片, 不便走云端视觉 API 时
    - 云端视觉限流时的高质量兜底 (qwen3.8-27b 多模态实测可用)

    【何时不适用】要极致速度的 OCR → 优先 mcp__glmvision__describe_image (云端, 秒级)

    【参数】
    - image_path: 图片绝对路径 (png/jpg/webp)
    - question: 针对图片的问题 (默认详细描述)
    - model: 留空=自动; 当前多模态 set 为 qwen3.8-27b
    """
    try:
        p = pathlib.Path(image_path).expanduser()
        if not p.is_file():
            return f"File not found: {image_path}"
        import base64
        suffix = p.suffix.lower().lstrip(".") or "png"
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "webp": "image/webp", "gif": "image/gif"}.get(suffix, "image/png")
        b64 = base64.b64encode(p.read_bytes()).decode()
        model_id = _resolve_model(model)
        messages = [{"role": "user", "content": [
            {"type": "text", "text": question},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
        ]}]
        return _chat(model_id, messages,
                     max_tokens=env_int("LOCAL_VISION_MAX_TOKENS", 768),
                     temperature=float(os.environ.get("LOCAL_TEMP", "0.7")))
    except Exception as e:  # noqa: BLE001
        return f"工具内部错误: {type(e).__name__}: {e}"


if __name__ == "__main__":
    huamcp.run(mcp)
