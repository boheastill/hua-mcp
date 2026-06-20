"""Emit MCP client config from registry.json — the single source of truth.

Both the Windows-side and WSL-side agents use the SAME config (mirrored networking
makes localhost:<port> resolve to whichever host runs each server), so every agent
can use every server.

Usage:
    python shared/gen_config.py            # print .mcp.json snippet to stdout
    python shared/gen_config.py > fleet-mcp.json
"""
import json
from pathlib import Path

REG = json.loads((Path(__file__).resolve().parent.parent / "registry.json").read_text("utf-8"))

servers = {}
for s in REG["servers"]:
    # Claude Code streamable-http MCP entry.
    servers[s["name"]] = {
        "type": "http",
        "url": f"http://localhost:{s['port']}/mcp",
    }

print(json.dumps({"mcpServers": servers}, indent=2, ensure_ascii=False))
