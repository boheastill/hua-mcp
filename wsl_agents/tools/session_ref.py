"""reff — Claude Code session id + resume command (migrated from mcp-servers/reff).

When the user says "switch terminals / continue in another window", this hands back
the current session id and the `reff r <sid>` command to paste in the new terminal.
"""
import json
import os
from pathlib import Path
from typing import Any, Dict


def my_session() -> Dict[str, Any]:
    """Get the current session id and resume command. Call when the user wants to
    switch terminals/windows and continue the same session."""
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if not sid:
        return {"error": "未检测到 CLAUDE_CODE_SESSION_ID"}

    projects_dir = Path.home() / ".claude" / "projects"
    model = ""
    backend = ""
    if projects_dir.exists():
        for project_dir in projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            session_file = project_dir / f"{sid}.jsonl"
            if session_file.exists():
                try:
                    with open(session_file, "r", encoding="utf-8", errors="ignore") as f:
                        for i, line in enumerate(f):
                            if i >= 50:
                                break
                            try:
                                obj = json.loads(line.strip())
                            except (json.JSONDecodeError, ValueError):
                                continue
                            msg = obj.get("message", {})
                            if msg.get("model"):
                                model = msg["model"]
                                m = model.lower()
                                if "mimo" in m:
                                    backend = "mimo"
                                elif "deepseek" in m:
                                    backend = "deepseek"
                                elif "claude" in m:
                                    backend = "anthropic"
                                break
                except OSError:
                    pass
                break

    return {
        "session_id": sid,
        "short_id": sid[:8],
        "backend": backend,
        "model": model,
        "resume_command": f"reff r {sid}",
        "note": "在新终端执行 resume_command 即可恢复此会话。如需换大脑：reff r <sid> mi/ds/cc",
    }


def register(mcp):
    mcp.tool()(my_session)
