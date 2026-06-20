"""Emit MCP client config by scanning every MCP's mcp.json.

Truth lives with each MCP (win/<name>/mcp.json, wsl/<name>/mcp.json) — there is no
central registry to hand-sync. Both the Windows-side and WSL-side agents use the SAME
output (mirrored networking makes localhost:<port> resolve to whichever host runs it).

    python gen_config.py            # print .mcp.json snippet
    python gen_config.py > fleet-mcp.json
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent

servers = {}
for mf in sorted(ROOT.glob("*/*/mcp.json")):  # win/<name>/, wsl/<name>/ (depth 2)
    if any(part.startswith("_") for part in mf.parts):  # skip _template etc.
        continue
    m = json.loads(mf.read_text(encoding="utf-8"))
    servers[m["name"]] = {"type": "http", "url": f"http://localhost:{m['port']}/mcp"}

print(json.dumps({"mcpServers": servers}, indent=2, ensure_ascii=False))
