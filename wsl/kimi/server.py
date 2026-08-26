"""kimi MCP — Kimi Code 订阅 (Moonshot, api.kimi.com/coding/v1) 的 API 门面。

2026-08-26 首建。模式取 local-model/glmvision: 无状态 API 门面, 非桥接
(zcode-bridge 已拆除, 本成员不做 agent 执行器, 只做模型能力委托)。

端点实测 (2026-08-26, 见 ~/agent/kimi/README.md):
  - sk-kimi- Key 只认 api.kimi.com/coding, moonshot.ai/.cn 全 401
  - 拒 developer 角色; system+max_tokens+reasoning_effort 正常
  - K3: 1M 上下文, effort low/high/max; K2.7 Coding 系列无 effort 档
  - 额度: 周额度池, 与 dsh provider(kimi/k3)/官方 CLI 共享同一订阅

Key 读取顺序: KIMI_API_KEY 环境变量 → ~/.kimi/key.txt (600, 不进 git)。

工具:
  kimi_ask(prompt, model?, system?, effort?, json_mode?)  — 文本委托
  kimi_vision(image_path, question?, model?)             — 看图 (K3 image_in)
"""
import base64
import os
import pathlib
import sys
import time
from typing import List

import requests

for _p in pathlib.Path(__file__).resolve().parents:
    if (_p / "huamcp.py").exists():
        sys.path.insert(0, str(_p))
        break
import huamcp  # noqa: E402

BASE = "https://api.kimi.com/coding/v1"
DEFAULT_MODEL = "k3"
# 支持 reasoning_effort 的模型 (K2.7 Coding 系列发了会报错)
EFFORT_MODELS = {"k3", "k3-256k"}
VALID_EFFORTS = {"low", "high", "max"}

_cache = {"ts": 0.0, "models": []}
_CACHE_TTL = 300.0

HINT = "端点 api.kimi.com/coding/v1 (sk-kimi Key 专属); dsh 原生路由 kimi/k3; 台账 ~/agent/kimi/README.md"


def env_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
        return value if value >= 0 else default
    except ValueError:
        return default


def _api_key() -> str:
    v = os.environ.get("KIMI_API_KEY", "").strip()
    if v:
        return v
    kf = pathlib.Path("~/.kimi/key.txt").expanduser()
    if kf.is_file():
        return kf.read_text(encoding="utf-8").strip()
    raise RuntimeError("缺少 KIMI_API_KEY (环境变量或 ~/.kimi/key.txt)")


def _list_models(force: bool = False) -> List[str]:
    now = time.time()
    if not force and _cache["models"] and now - _cache["ts"] < _CACHE_TTL:
        return _cache["models"]
    try:
        resp = requests.get(f"{BASE}/models",
                            headers={"Authorization": f"Bearer {_api_key()}"},
                            timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise RuntimeError(f"Kimi 端点不可达/未授权: {type(e).__name__}: {e}; {HINT}") from e
    ids = [m.get("id", "") for m in resp.json().get("data", []) if m.get("id")]
    if not ids:
        raise RuntimeError(f"Kimi /models 返回空; {HINT}")
    _cache["models"] = ids
    _cache["ts"] = now
    return ids


def _resolve_model(model: str) -> str:
    """model 参数 → 端点真名。空/mono→默认 k3; 必须命中活列表(防 typo 白烧额度)。"""
    key = (model or "").strip() or DEFAULT_MODEL
    live = _list_models()
    if key in live:
        return key
    raise RuntimeError(f"模型 {key!r} 不在端点模型列表 {live}; {HINT}")


def _chat(model_id: str, messages: list, max_tokens: int, effort: str = "") -> str:
    payload = {
        "model": model_id,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": False,
    }
    # 只给 K3 家族发 effort 档位 (K2.7 Coding 系列不认)
    if effort and model_id in EFFORT_MODELS:
        payload["reasoning_effort"] = effort
    try:
        resp = requests.post(f"{BASE}/chat/completions",
                             headers={"Authorization": f"Bearer {_api_key()}"},
                             json=payload,
                             timeout=env_int("KIMI_TIMEOUT", 300))
        resp.raise_for_status()
    except requests.RequestException as e:
        raise RuntimeError(f"Kimi 调用失败: {type(e).__name__}: {e}; {HINT}") from e
    data = resp.json()
    if data.get("error"):
        return f"Kimi 端点错误: {data['error']}"
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    return content.strip() or "(空回复)"


mcp = huamcp.server(__file__)


@mcp.tool()
def kimi_ask(prompt: str, model: str = "", system: str = "",
             effort: str = "low", json_mode: bool = False) -> str:
    """把任务委托给 Moonshot Kimi 订阅模型 (K3 旗舰 1M 上下文; 与 glm/local 并列的云端委托通道)。

    【何时用】
    - 需要 Kimi/K3 特长的活: 超长文档/代码库摘要(1M ctx)、中文深度推理
    - GLM 订阅限流时的第二云端池 (同一把 Key 也是 dsh 的 kimi/k3 路由)
    - 分类/抽取/润色/翻译等轻量委托 (默认 low effort, 便宜快速)

    【何时不适用】
    - 免费离线优先的轻活 → mcp__local-model__local_ask (lb 台式机, 零额度)
    - 看图急活 → mcp__glmvision__describe_image (秒级); kimi_vision 是高质量兜底
    - agent 式自主执行任务 → 本舰队不做执行器委托 (zcode-bridge 已拆除)

    【参数】
    - prompt: 任务提示词 (自包含)
    - model: 留空=k3; 可选 k3-256k / kimi-for-coding / kimi-for-coding-highspeed
    - system: 可选系统提示词
    - effort: K3 家族思考档 low/high/max (默认 low=委托经济档; 难题给 high/max);
              K2.7 Coding 系列无此参数, 传了会被忽略
    - json_mode: 强制只输出一个合法 JSON 对象
    """
    try:
        model_id = _resolve_model(model)
        if effort and effort not in VALID_EFFORTS:
            raise RuntimeError(f"effort 只能是 {sorted(VALID_EFFORTS)} 之一, 收到 {effort!r}")
        sys_content = system.strip() or "你是用户的云端委托模型, 直接给出有用、完整的回答。"
        if json_mode:
            sys_content += " 只输出一个合法的 JSON 对象, 不要输出任何其他文字、解释或代码块标记。"
        messages = [{"role": "system", "content": sys_content},
                    {"role": "user", "content": prompt}]
        return _chat(model_id, messages,
                     max_tokens=env_int("KIMI_MAX_TOKENS", 4096),
                     effort=effort)
    except Exception as e:  # noqa: BLE001
        return f"工具内部错误: {type(e).__name__}: {e}"


@mcp.tool()
def kimi_vision(image_path: str, question: str = "详细描述这张图片的内容",
                model: str = "") -> str:
    """用 Kimi 订阅模型看图 (K3 多模态, 高质量兜底档)。

    【何时用】
    - glmvision 限流/降级时的高质量云端兜底 (K3 旗舰视觉)
    - 复杂图表/长文档截图/密集 UI 的精细判读

    【何时不适用】要极致速度 → mcp__glmvision__describe_image (秒级);
    隐私敏感图 → mcp__local-model__local_vision (数据不出局域网)。

    【参数】
    - image_path: 图片绝对路径 (png/jpg/jpeg/webp/gif)
    - question: 针对图片的问题 (默认详细描述)
    - model: 留空=k3 (1M 上下文, 收长图长文档截图不慌)
    """
    try:
        p = pathlib.Path(image_path).expanduser()
        if not p.is_file():
            return f"File not found: {image_path}"
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
                     max_tokens=env_int("KIMI_VISION_MAX_TOKENS", 2048))
    except Exception as e:  # noqa: BLE001
        return f"工具内部错误: {type(e).__name__}: {e}"


if __name__ == "__main__":
    huamcp.run(mcp)
