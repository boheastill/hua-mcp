"""Template MCP — copy this whole folder to add a new MCP.

  1. cp -r _template win/<name>   (or wsl/<name>)
  2. edit mcp.json: name (== dir name), port (win 8001-8099 / wsl 8100+), os
  3. write your @mcp.tool() functions below
  4. put deps in requirements.txt
  5. ./fleet.sh validate && ./fleet.sh test     # catch mistakes before running
  6. ./fleet.sh up   (wsl)   or re-run win/install-autostart.ps1 (win)

fleet.sh and gen_config.py discover this MCP by scanning */*/mcp.json — no central
file to edit. huamcp handles bind/health/auth/transport; you only write tools.
"""
import pathlib
import sys
from typing import Any, Dict

for _p in pathlib.Path(__file__).resolve().parents:
    if (_p / "huamcp.py").exists():
        sys.path.insert(0, str(_p))
        break
import huamcp  # noqa: E402

mcp = huamcp.server(__file__)


@mcp.tool()
def example_tool(name: str = "world") -> Dict[str, Any]:
    """One-line description the agent will see. Say exactly what it does and when to use it."""
    return {"hello": name}


if __name__ == "__main__":
    huamcp.run(mcp)
