"""Template MCP — copy this whole folder to add a new MCP.

Steps to add an MCP:
  1. cp -r _template win/<name>   (or wsl/<name>)
  2. edit mcp.json: name, port (win 8001-8099 / wsl 8100+), os ("win" | "wsl")
  3. write your @mcp.tool() functions below
  4. put deps in requirements.txt
  5. ./fleet.sh up   (wsl)   or re-run win/install-autostart.ps1 (win)

That's it — fleet.sh and gen_config.py discover it by scanning */*/mcp.json.
A self-contained server.py: read own mcp.json, register tools, serve streamable-http.
"""
import json
import pathlib
import sys
from typing import Any, Dict

from mcp.server.fastmcp import FastMCP

META = json.loads((pathlib.Path(__file__).resolve().parent / "mcp.json").read_text(encoding="utf-8"))
mcp = FastMCP(META["name"], host="0.0.0.0", port=META["port"])


@mcp.tool()
def example_tool(name: str = "world") -> Dict[str, Any]:
    """One-line description the agent will see. Say exactly what it does and when to use it."""
    return {"hello": name}


@mcp.custom_route("/health", methods=["GET"])
async def _health(request):
    from starlette.responses import JSONResponse

    return JSONResponse({"ok": True, "mcp": META["name"], "os": META["os"], "port": META["port"]})


if __name__ == "__main__":
    mcp.run() if "--stdio" in sys.argv else mcp.run(transport="streamable-http")
