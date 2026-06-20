"""Shared fleet runtime for hua-mcp.

Goal: make adding servers and tools trivial so the fleet can scale to "many".

- Port / transport come from ``registry.json`` (the single source of truth) — never
  hard-coded in a server again.
- Tools auto-register: drop a ``tools/<name>.py`` that defines ``def register(mcp): ...``
  and it is picked up automatically. No editing the server file.
- Every server gets a uniform ``GET /health`` for fleet monitoring.

A server file is therefore ~5 lines:

    import fleet
    if __name__ == "__main__":
        fleet.serve("wsl-agents")   # name must exist in registry.json

``fleet.serve`` discovers a sibling ``tools/`` package relative to the *calling*
server file's directory.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import inspect
import json
import pkgutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # hua-mcp/
REGISTRY = json.loads((ROOT / "registry.json").read_text(encoding="utf-8"))


def entry(name: str) -> dict:
    for s in REGISTRY.get("servers", []):
        if s["name"] == name:
            return s
    raise KeyError(f"server '{name}' not found in registry.json")


def _autoload_tools(mcp, tools_dir: Path) -> list[str]:
    """Import every ``tools/<mod>.py`` and call its ``register(mcp)`` if present."""
    if not tools_dir.is_dir():
        return []
    if str(tools_dir.parent) not in sys.path:
        sys.path.insert(0, str(tools_dir.parent))
    loaded: list[str] = []
    pkg = importlib.import_module("tools")
    for mod in pkgutil.iter_modules(pkg.__path__):
        if mod.name.startswith("_"):
            continue
        module = importlib.import_module(f"tools.{mod.name}")
        register = getattr(module, "register", None)
        if callable(register):
            register(mcp)
            loaded.append(mod.name)
    return loaded


def build(name: str):
    """Construct a FastMCP for ``name`` with host/port from the registry + /health."""
    from mcp.server.fastmcp import FastMCP

    e = entry(name)
    mcp = FastMCP(name, host="0.0.0.0", port=int(e["port"]))

    @mcp.custom_route("/health", methods=["GET"])
    async def _health(request):  # noqa: ANN001
        from starlette.responses import JSONResponse

        return JSONResponse(
            {"ok": True, "server": name, "env": e.get("env"), "port": e["port"]}
        )

    return mcp, e


def serve(name: str) -> None:
    """Build server ``name``, auto-load tools from the caller's ``tools/`` dir, run it.

    CLI: default = stdio (single local client). ``--http`` = networked transport from
    the registry (streamable-http). ``--sse`` = legacy SSE if ever needed.
    """
    # Locate the calling server file so we find ITS tools/ dir (not fleet.py's).
    caller_file = Path(inspect.stack()[1].filename).resolve()
    tools_dir = caller_file.parent / "tools"

    mcp, e = build(name)
    loaded = _autoload_tools(mcp, tools_dir)

    parser = argparse.ArgumentParser(description=f"hua-mcp server: {name}")
    parser.add_argument("--http", action="store_true", help="networked transport (registry)")
    parser.add_argument("--sse", action="store_true", help="legacy SSE transport")
    args = parser.parse_args()

    mode = "stdio"
    if args.sse:
        mode = "sse"
    elif args.http:
        mode = e.get("transport", "streamable-http")

    print(f"[{name}] tools={loaded or '(none)'} :{e['port']} transport={mode}", file=sys.stderr)

    if mode == "stdio":
        mcp.run()
    else:
        mcp.run(transport=mode)
