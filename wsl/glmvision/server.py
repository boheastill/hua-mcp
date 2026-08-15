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
    """用智谱 GLM 视觉模型识别本地图片内容。

path 是图片文件的绝对路径(建议, 服务器无法感知调用方工作区); question 是
针对图片的具体问题, 可省略(默认详细描述全图)。纯文本主模型看图用这个工具。
model 可选: 默认 glm-5v-turbo(视觉旗舰); 也可指定 glm-4.6v-flash(免费, 限速)。
"""
    p = pathlib.Path(path).expanduser()
    if not p.is_file():
        return f"图片文件不存在: {path}"
    mime = mimetypes.guess_type(str(p))[0] or ""
    if not mime.startswith("image/"):
        return f"不支持的图片格式: {path} (支持 png/jpg/jpeg/webp/gif/bmp)"
    key = _key()
    if not key:
        return "缺少 GLM_API_KEY (环境变量或 ~/.glm/key.txt)"
    b64 = base64.b64encode(p.read_bytes()).decode()
    q = question.strip() or "请详细描述这张图片的内容。"
    body: dict[str, Any] = {
        "model": model.strip() or "glm-5v-turbo",
        "max_tokens": 4096,
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
        data = r.json()
    except Exception as e:  # noqa: BLE001 — 工具要给 agent 可读的错误而不是抛出
        return f"GLM API 请求失败: {e}"
    if r.status_code != 200:
        return f"GLM API 错误 ({r.status_code}): {str(data)[:400]}"
    return data.get("choices", [{}])[0].get("message", {}).get("content") or "(空回复)"


if __name__ == "__main__":
    huamcp.run(mcp)
