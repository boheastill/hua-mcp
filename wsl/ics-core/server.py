"""ics-core MCP — ICS-Core 跨设备消息流与文件传输工具。

工具:
  list_messages(channel?)
  read_message(item_id)
  push_message(text, device?, channel?)
  push_file(file_path, device?, channel?)
  manage_message(item_id, action)
"""
import os
import pathlib
import sys
from typing import Any, Dict, List, Optional
import requests

for _p in pathlib.Path(__file__).resolve().parents:
    if (_p / "huamcp.py").exists():
        sys.path.insert(0, str(_p))
        break
import huamcp  # noqa: E402

ICS_BASE_URL = os.environ.get("ICS_BASE_URL", "https://flow.bohea.us")
ICS_TOKEN = os.environ.get("ICS_TOKEN", "006e91db7de25746bd029895f9e5f45b")

mcp = huamcp.server(__file__)


def _get_headers() -> Dict[str, str]:
    return {"X-Auth-Token": ICS_TOKEN}


@mcp.tool()
def list_messages(channel: str = "") -> List[Dict[str, Any]]:
    """列出 ICS-Core 流中的当前消息与文件卡片 (按最新时间倒序)。

    【参数】channel: 可选 channel 命名空间
    """
    try:
        params = {"channel": channel} if channel else {}
        resp = requests.get(f"{ICS_BASE_URL}/api/list", headers=_get_headers(), params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:  # noqa: BLE001
        return [{"error": f"list_messages failed: {e}"}]


@mcp.tool()
def read_message(item_id: str) -> str:
    """读取指定消息或文件的原始内容。

    【参数】item_id: 消息/文件唯一 ID (如 'upwork/1780183356_pc_text.txt')
    """
    try:
        resp = requests.get(f"{ICS_BASE_URL}/api/download/{item_id}", headers=_get_headers(), timeout=15)
        resp.raise_for_status()
        return resp.text
    except Exception as e:  # noqa: BLE001
        return f"read_message failed: {e}"


@mcp.tool()
def push_message(text: str, device: str = "ai", channel: str = "") -> Dict[str, Any]:
    """向 ICS-Core 流推送一条文本消息。

    【参数】text: 文本内容; device: 发送设备标识 (默认 'ai'); channel: 可选频道
    """
    try:
        multipart_data = {
            "text": (None, text),
            "device": (None, device),
        }
        params = {"channel": channel} if channel else {}
        resp = requests.post(f"{ICS_BASE_URL}/api/push", headers=_get_headers(), params=params, files=multipart_data, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:  # noqa: BLE001
        return {"error": f"push_message failed: {e}"}


@mcp.tool()
def push_file(file_path: str, device: str = "ai", channel: str = "") -> Dict[str, Any]:
    """向 ICS-Core 流上传一个本地文件。

    【参数】file_path: 本地文件绝对路径; device: 设备标识; channel: 可选频道
    """
    try:
        p = pathlib.Path(file_path).expanduser()
        if not p.is_file():
            return {"error": f"File not found: {file_path}"}
        params = {"channel": channel} if channel else {}
        with open(p, "rb") as f:
            multipart_data = {
                "file": (p.name, f),
                "device": (None, device),
            }
            resp = requests.post(f"{ICS_BASE_URL}/api/push", headers=_get_headers(), params=params, files=multipart_data, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:  # noqa: BLE001
        return {"error": f"push_file failed: {e}"}


@mcp.tool()
def manage_message(item_id: str, action: str) -> Dict[str, Any]:
    """管理 ICS-Core 流中的消息 (pin / unpin / delete)。"""
    try:
        if action not in ("pin", "unpin", "delete"):
            return {"error": f"action must be one of: 'pin', 'unpin', 'delete', got {action!r}"}
        payload = {"id": item_id, "action": action}
        resp = requests.post(f"{ICS_BASE_URL}/api/action", headers=_get_headers(), json=payload, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:  # noqa: BLE001
        return {"error": f"manage_message failed: {e}"}


if __name__ == "__main__":
    huamcp.run(mcp)
