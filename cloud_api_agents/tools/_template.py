"""Tool module template — copy me to add a tool.

Rules (enforced by shared/fleet.py auto-discovery):
  • File goes in this server's tools/ directory. Name it after the capability.
  • Files starting with "_" are IGNORED (so this template never loads).
  • Define plain functions with clear docstrings (the docstring is what the agent reads).
  • Expose `register(mcp)` that decorates each function with `mcp.tool()`.
  • Put any new deps in this server's requirements.txt.
"""
from typing import Any, Dict


def example_tool(name: str = "world") -> Dict[str, Any]:
    """One-line description the agent will see. Say exactly what it does and when to use it."""
    return {"hello": name}


def register(mcp):
    mcp.tool()(example_tool)
