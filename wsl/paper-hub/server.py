"""paper-hub MCP — 异步物理人机交互中枢 (Human-in-the-Physical-Loop)。

提供核心工具:
1. create_paper_task: AI 创建带密级页眉、交互选项与手机扫码二维码的物理纸张任务并打印
2. check_task_feedback: 检查人类是否已用手机扫码并提交了决策/批注
3. list_paper_tasks: 列出所有历史纸张交互任务及当前状态
"""
import json
import os
import pathlib
import sys
from typing import Any

import requests

for _p in pathlib.Path(__file__).resolve().parents:
    if (_p / "huamcp.py").exists():
        sys.path.insert(0, str(_p))
        break
import huamcp  # noqa: E402

HUB_BASE = os.environ.get("PAPER_HUB_URL", "http://127.0.0.1:3088").rstrip("/")

mcp = huamcp.server(__file__)


@mcp.tool()
def create_paper_task(
    title: str,
    content: str,
    security_level: str = "内部",
    category: str = "技术",
    agent_id: str = "AI-Agent",
    model_name: str = "deepseek-r1",
    choices: list[str] | None = None,
    auto_print: bool = True,
) -> str:
    """创建并打印一份带有密级页眉、决策选择框与手机交互二维码的物理纸张任务。

    【何时用】
    当你（AI Agent）需要人类离开电脑进行深度思考、方案决策或审批，并期望人类在物理纸张上阅读后通过手机扫码回传决策时调用。

    【参数】
    title: 任务/方案标题 (如 "2026年架构重构路线审批")。
    content: 正文内容或方案说明。
    security_level: 密级，支持 "公开" / "内部" / "秘密" / "机密" / "绝密" (默认 "内部")。
    category: 类别，支持 "技术" / "业务" / "思考" / "私人" / "决策" / "告警" (默认 "技术")。
    agent_id: 发起本任务的 Agent 名称 (如 "CodeArchitect")。
    model_name: 当前使用的模型名称 (如 "deepseek-r1")。
    choices: 可选，单选决策选项列表 (如 ["采纳方案A", "采纳方案B", "驳回修改"])。
    auto_print: 是否立即驱动物理打印机出纸 (默认 True)。

    【返回】
    包含 task_id、short_id、手机扫码直达 URL 和 PDF 路径的确认信息。
    """
    widgets: list[dict[str, Any]] = []
    if choices:
        widgets.append(
            {
                "id": "decision_choice",
                "type": "SINGLE_CHOICE",
                "label": "请确认本次决策采纳方案：",
                "options": choices,
            }
        )

    payload = {
        "title": title.strip() or "AI 物理交互任务",
        "content": content.strip(),
        "security_level": security_level.strip() or "内部",
        "category": category.strip() or "技术",
        "agent_id": agent_id.strip() or "AI-Agent",
        "model_name": model_name.strip() or "deepseek-r1",
        "widgets": widgets,
        "auto_print": auto_print,
    }

    try:
        r = requests.post(f"{HUB_BASE}/api/tasks/create", json=payload, timeout=10)
        if r.status_code == 200:
            data = r.json()
            return (
                f"✅ 物理交互任务已创建并成功下发打印！\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🆔 任务编号: {data.get('task_id')} (短码: #{data.get('short_id')})\n"
                f"🏷️ 密级/类别: [{security_level} / {category}]\n"
                f"📱 手机扫码地址: {data.get('qr_url')}\n"
                f"📄 查看/下载 PDF: {HUB_BASE}{data.get('pdf_url')}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💡 人类在物理纸张上阅读后，用手机扫码提交的数据将自动落库。\n"
                f"你可以通过 `check_task_feedback(task_id='{data.get('task_id')}')` 检查人类是否已反馈。"
            )
        return f"❌ 创建任务失败: HTTP {r.status_code} - {r.text}"
    except Exception as e:
        return f"❌ 无法连接到 paper-hub 服务 ({HUB_BASE}): {e}"


@mcp.tool()
def check_task_feedback(task_id: str) -> str:
    """检查指定物理任务的状态，查看人类是否已经用手机扫码并提交了决策或意见。

    【参数】
    task_id: 任务唯一编号 (例如 "task_20260821_213443_105f")。

    【返回】
    人类填写的决策选项、批注随笔、提交时间与当前状态。
    """
    try:
        r = requests.get(f"{HUB_BASE}/api/tasks/{task_id.strip()}", timeout=5)
        if r.status_code == 200:
            task = r.json()
            status = task.get("status")
            if status == "RESPONDED":
                fb = task.get("human_feedback", {})
                return (
                    f"🎉 【人类已反馈】任务: {task.get('title')} (#{task.get('short_id')})\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"⏰ 反馈时间: {fb.get('submitted_at')}\n"
                    f"📱 决策数据: {json.dumps(fb.get('payload', {}), ensure_ascii=False)}\n"
                    f"💬 补充意见: {fb.get('comment') or '(无补充意见)'}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"👉 请根据人类的上述决策继续执行后续任务。"
                )
            return (
                f"⏳ 任务状态: 【{status}】(等待人类手机扫码中)\n"
                f"标题: {task.get('title')}\n"
                f"打印时间: {task.get('created_at')}\n"
                f"手机扫码地址: {task.get('qr_url')}"
            )
        return f"❌ 任务未找到 ({task_id}): HTTP {r.status_code}"
    except Exception as e:
        return f"❌ 查询异常: {e}"


@mcp.tool()
def list_paper_tasks() -> str:
    """列出所有历史物理纸张交互任务及其当前状态。"""
    try:
        r = requests.get(f"{HUB_BASE}/api/tasks", timeout=5)
        if r.status_code == 200:
            tasks = r.json()
            if not tasks:
                return "当前没有任何物理交互任务记录。"
            lines = [f"📋 共找到 {len(tasks)} 条物理任务记录:"]
            for t in tasks[:15]:
                status_icon = "✅" if t.get("status") == "RESPONDED" else "⏳"
                lines.append(
                    f"  {status_icon} [{t.get('status')}] #{t.get('short_id')} "
                    f"[{t.get('security_level')}/{t.get('category')}] "
                    f"{t.get('title')} ({t.get('agent_id')})"
                )
            return "\n".join(lines)
        return f"❌ 获取列表失败: HTTP {r.status_code}"
    except Exception as e:
        return f"❌ 查询异常: {e}"


if __name__ == "__main__":
    huamcp.run(mcp)
