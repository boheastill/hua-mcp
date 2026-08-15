"""GLM vision MCP — 用智谱 GLM-5V-Turbo 识别本地图片。

工具: describe_image(path, question?)
Key 读取顺序: GLM_API_KEY 环境变量 → ~/.glm/key.txt / key.ps1 (不硬编码)。
"""
import pathlib
import sys

for _p in pathlib.Path(__file__).resolve().parents:
    if (_p / "huamcp.py").exists():
        sys.path.insert(0, str(_p))
        break
import huamcp  # noqa: E402

import base64
import mimetypes
import os
import re
from typing import Any

import requests

API = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

mcp = huamcp.server(__file__)


def _sniff_image_mime(p: pathlib.Path) -> str:
    """按文件头魔数识别图片类型;返回空串表示不是已知图片。

    附件/临时文件经常没有扩展名(如 DSH 内容寻址附件),mimetypes 只会看后缀,
    这里先嗅探字节再退回后缀判断。
    """
    try:
        head = p.read_bytes()[:32]
    except OSError:
        return ""
    for sig, mime in (
        (b"\x89PNG\r\n\x1a\n", "image/png"),
        (b"\xff\xd8\xff", "image/jpeg"),
        (b"GIF87a", "image/gif"),
        (b"GIF89a", "image/gif"),
        (b"RIFF", "image/webp"),  # 还需 offset 8 处的 WEBP 标记
        (b"BM", "image/bmp"),
    ):
        if head.startswith(sig):
            if mime == "image/webp" and head[8:12] != b"WEBP":
                continue
            return mime
    return ""


def _key() -> str:
    v = os.environ.get("GLM_API_KEY", "").strip()
    if v:
        return v
    home = pathlib.Path.home()
    for name in ("key.txt", "key.ps1"):
        p = home / ".glm" / name
        try:
            for raw in p.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                m = re.search(r'"([^"]+)"', line)
                return m.group(1) if m else line
        except OSError:
            continue
    return ""


@mcp.tool()
def describe_image(path: str, question: str = "", model: str = "glm-5v-turbo") -> str:
    """用智谱 GLM 视觉模型识别本地图片内容 — 看图的第一选择。

【何时用】主模型是纯文本(如 DeepSeek/GLM 文本档)时需要看图、OCR、
识别截图/设计稿/图表: 这是最快最便宜的看图通道(秒级响应, 不耗 agy 额度,
不留会话)。遇到图就用它, 不要绕道到 agy。

【何时别用】需要"看图 + 深度推理/联网/多步操作"的复合任务 → 交给
mcp__agy__agy_ask(或 mcp__agy-sdk__agy_sdk_ask), 它们能自己看图并继续推理。

【参数】path 图片绝对路径(建议; 服务器无法感知调用方工作区); question 针对
图片的具体问题(可选, 默认详细描述); model 默认 glm-5v-turbo(视觉旗舰)。
429(余额/限速)时自动降级: glm-5v-turbo → glm-4.6v-flash → glm-4v-flash。
"""
    p = pathlib.Path(path).expanduser()
    if not p.is_file():
        return f"图片文件不存在: {path}"
    mime = _sniff_image_mime(p) or (mimetypes.guess_type(str(p))[0] or "")
    if not mime.startswith("image/"):
        return f"不支持的图片格式: {path} (支持 png/jpg/jpeg/webp/gif/bmp)"
    key = _key()
    if not key:
        return "缺少 GLM_API_KEY (环境变量或 ~/.glm/key.txt)"
    b64 = base64.b64encode(p.read_bytes()).decode()
    q = question.strip() or "请详细描述这张图片的内容。"

    def _post(model_id: str, max_tokens: int) -> tuple[Any, Any]:
        body: dict[str, Any] = {
            "model": model_id,
            "max_tokens": max_tokens,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                        {"type": "text", "text": q},
                    ],
                }
            ],
        }
        try:
            r = requests.post(
                API,
                headers={"content-type": "application/json", "Authorization": f"Bearer {key}"},
                json=body,
                timeout=180,
            )
            return r, r.json()
        except Exception as e:  # noqa: BLE001 — 工具要给 agent 可读的错误而不是抛出
            raise RuntimeError(f"GLM API 请求失败: {e}") from e

    # 降级链: 付费旗舰 → 新一代免费档 → 老一代免费档(后者 max_tokens 上限 1024)。
    # 只对 429(余额/限速)降级; 其他错误(参数/鉴权等)原样上报, 不掩盖。
    CHAIN: list[tuple[str, int]] = [
        ("glm-5v-turbo", 4096),
        ("glm-4.6v-flash", 4096),
        ("glm-4v-flash", 1024),
    ]
    requested = model.strip() or "glm-5v-turbo"
    start = next((i for i, (m, _) in enumerate(CHAIN) if m == requested), 0)
    tried: list[str] = []
    r: Any = None
    data: Any = None
    for model_id, max_tokens in CHAIN[start:]:
        tried.append(model_id)
        try:
            r, data = _post(model_id, max_tokens)
        except RuntimeError as e:
            return str(e)
        if r.status_code == 200:
            break
        if r.status_code != 429:
            break
    if r.status_code != 200:
        tail = " → ".join(tried)
        return f"GLM API 错误 ({r.status_code}, 尝试过 {tail}): {str(data)[:400]}"
    content = data.get("choices", [{}])[0].get("message", {}).get("content") or "(空回复)"
    if len(tried) > 1:
        return f"[已自动降级到 {tried[-1]}({' → '.join(tried[:-1])} 不可用)]\n" + content
    return content


if __name__ == "__main__":
    huamcp.run(mcp)
