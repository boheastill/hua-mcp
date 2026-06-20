"""huamcp — tiny shared runtime for every MCP in this fleet.

It centralizes the *plumbing* (bind address, /health, auth, transport) so each
server.py only declares its tools. It deliberately does NOT discover tools — you
still write `@mcp.tool()` explicitly. One place to enforce the cross-cutting rules:

  • Secure by default: bind 127.0.0.1. Public (0.0.0.0) only via `--public` or
    HUAMCP_PUBLIC=1. Under WSL2 mirrored networking, 127.0.0.1 is still reachable
    Win<->WSL, so the secure default does not break the fleet.
  • Uniform GET /health: {ok, mcp, os, port, public}.
  • Optional Bearer auth: if mcp.json sets "auth_env" (or HUAMCP_TOKEN is set) and
    that env var holds a token, every route except /health requires
    `Authorization: Bearer <token>`. Unset => open (local/dev). Going public is a
    config flip, not a rewrite.

Usage (a whole server.py):

    import pathlib, sys
    for _p in pathlib.Path(__file__).resolve().parents:
        if (_p / "huamcp.py").exists(): sys.path.insert(0, str(_p)); break
    import huamcp

    mcp = huamcp.server(__file__)

    @mcp.tool()
    def my_tool(): ...

    if __name__ == "__main__":
        huamcp.run(mcp)
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

from mcp.server.fastmcp import FastMCP


def load_meta(server_file: str) -> dict:
    return json.loads((pathlib.Path(server_file).resolve().parent / "mcp.json").read_text("utf-8"))


def _token_for(meta: dict) -> str | None:
    env = meta.get("auth_env")
    if env and os.environ.get(env):
        return os.environ[env]
    return os.environ.get("HUAMCP_TOKEN") or None


def server(server_file: str) -> FastMCP:
    """Build a FastMCP for the MCP whose dir contains ``server_file``'s mcp.json."""
    meta = load_meta(server_file)
    public = "--public" in sys.argv or os.environ.get("HUAMCP_PUBLIC") == "1"
    host = "0.0.0.0" if public else "127.0.0.1"
    port = int(os.environ.get("HUAMCP_PORT", meta["port"]))

    mcp = FastMCP(meta["name"], host=host, port=port)
    mcp._hua = {"meta": meta, "host": host, "port": port, "public": public, "token": _token_for(meta)}

    @mcp.custom_route("/health", methods=["GET"])
    async def _health(request):  # noqa: ANN001
        from starlette.responses import JSONResponse

        return JSONResponse(
            {"ok": True, "mcp": meta["name"], "os": meta.get("os"), "port": port, "public": public}
        )

    return mcp


def run(mcp: FastMCP) -> None:
    """Serve: stdio with --stdio, else streamable-http (+ Bearer auth if a token is set)."""
    if "--stdio" in sys.argv:
        mcp.run()
        return

    hua = getattr(mcp, "_hua", {})
    token = hua.get("token")
    if not token:
        mcp.run(transport="streamable-http")
        return

    # Token set -> wrap the streamable-http app with Bearer auth (everything but /health).
    import uvicorn
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    class _BearerAuth(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            if request.url.path == "/health":
                return await call_next(request)
            if request.headers.get("authorization") != f"Bearer {token}":
                return JSONResponse({"detail": "unauthorized"}, status_code=401)
            return await call_next(request)

    app = mcp.streamable_http_app()
    app.add_middleware(_BearerAuth)
    uvicorn.run(app, host=hua["host"], port=hua["port"])
