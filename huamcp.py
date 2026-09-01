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
import threading
import time
import uuid

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
    public = "--public" in sys.argv or os.environ.get("HUAMCP_PUBLIC") == "1" or bool(meta.get("public"))
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


# ------------------------------------------------------------------ relay
# For remote MCP upstreams (BigModel coding-plan's web_search_prime /
# web_reader / zread): a transparent streamable-http relay keeps the upstream
# key in ONE file (~/.glm/key.txt) so every client wires to plain loopback
# with zero credentials, while tools/schema pass through as-is. A relay
# member's server.py is exactly:
#
#     app = huamcp.relay(__file__, "https://open.bigmodel.cn/api/mcp/<x>/mcp")
#     if __name__ == "__main__":
#         huamcp.run_relay(app, __file__)


def _bearer_key(auth_env: str, key_paths: tuple[str, ...]) -> str:
    """Key lookup: env var first, then first non-comment line of each file
    (a quoted substring wins, so both plain keys and `key.ps1`-style files work).
    Read per request so a rotated key needs no restart."""
    v = os.environ.get(auth_env, "").strip()
    if v:
        return v
    import re

    for raw_path in key_paths:
        try:
            lines = pathlib.Path(raw_path).expanduser().read_text("utf-8").splitlines()
        except OSError:
            continue
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            m = re.search(r'"([^"]+)"', line)
            return m.group(1) if m else line
    return ""


def relay(
    server_file: str,
    upstream: str,
    auth_env: str = "GLM_API_KEY",
    key_paths: tuple[str, ...] = ("~/.glm/key.txt",),
    auth_required: bool = True,
):
    """Starlette app: local ``/health`` + ``/mcp`` transparently relayed to a
    remote streamable-http MCP. POST/GET/DELETE are forwarded with the session
    headers and an injected ``Authorization: Bearer <key>`` (when a key is
    found; free upstreams pass ``auth_required=False`` to skip auth entirely).
    No MCP protocol handling happens here — bytes pass through, upstream tools
    surface as-is (upstream errors like 401 quota pass through too, unmasked)."""
    import httpx
    from starlette.applications import Starlette
    from starlette.background import BackgroundTask
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response, StreamingResponse
    from starlette.routing import Route

    meta = load_meta(server_file)
    # hop-by-hop / framing headers must never be copied across the relay
    FWD_REQ = ("content-type", "accept", "mcp-session-id", "mcp-protocol-version", "last-event-id")
    FWD_RES = ("content-type", "mcp-session-id", "mcp-protocol-version")
    client = httpx.AsyncClient(timeout=httpx.Timeout(connect=15.0, read=600.0, write=120.0, pool=15.0))

    async def _health(request: Request) -> Response:  # noqa: ANN001
        return JSONResponse(
            {
                "ok": True,
                "mcp": meta["name"],
                "os": meta.get("os"),
                "port": int(os.environ.get("HUAMCP_PORT", meta["port"])),
                "upstream": upstream,
                "auth_required": auth_required,
                "key_ok": bool(_bearer_key(auth_env, key_paths)),
            }
        )

    async def _proxy(request: Request) -> Response:  # noqa: ANN001
        key = _bearer_key(auth_env, key_paths)
        if not key and auth_required:
            return JSONResponse(
                {"detail": f"upstream key missing: set {auth_env} or write {key_paths[0]}"},
                status_code=503,
            )
        headers = {k: v for k, v in request.headers.items() if k.lower() in FWD_REQ}
        if key:
            headers["authorization"] = f"Bearer {key}"
        url = upstream + (f"?{request.url.query}" if request.url.query else "")
        # GET opens the (possibly long-idle) server->client stream: no read timeout there
        timeout = httpx.Timeout(
            connect=15.0,
            read=None if request.method == "GET" else 600.0,
            write=120.0,
            pool=15.0,
        )
        try:
            req = client.build_request(request.method, url, headers=headers, content=request.stream())
            resp = await client.send(req, stream=True)
        except httpx.HTTPError as e:
            return JSONResponse({"detail": f"upstream unreachable: {e}"}, status_code=502)
        out_headers = {k: v for k, v in resp.headers.items() if k.lower() in FWD_RES}

        async def _passthrough():
            async for chunk in resp.aiter_bytes():
                yield chunk

        return StreamingResponse(
            _passthrough(),
            status_code=resp.status_code,
            headers=out_headers,
            background=BackgroundTask(resp.aclose),
        )

    return Starlette(
        routes=[
            Route("/health", _health, methods=["GET"]),
            Route("/mcp", _proxy, methods=["POST", "GET", "DELETE"]),
        ]
    )


def run_relay(app, server_file: str) -> None:
    """Serve a relay app under the same bind/public/port rules as run()."""
    import uvicorn

    meta = load_meta(server_file)
    public = "--public" in sys.argv or os.environ.get("HUAMCP_PUBLIC") == "1" or bool(meta.get("public"))
    host = "0.0.0.0" if public else "127.0.0.1"
    port = int(os.environ.get("HUAMCP_PORT", meta["port"]))
    uvicorn.run(app, host=host, port=port)


# ------------------------------------------------------------ background tasks
# Some clients hard-timeout MCP tool calls (ZCode: 30s) while legitimate tools
# run minutes (agy_ask / kimi_ask). Members submit the slow body via
# submit_task() and answer fast — finished result, or a task_id the agent polls
# with its *_task_result tool — so every client, timeout or not, gets served.
# Bonus: the heavy work churns on a daemon thread, so the member's HTTP loop
# stays responsive while a long call is in flight.

_tasks: dict = {}
_tasks_lock = threading.Lock()


def submit_task(fn, *args, max_concurrent: int = 3, grace_s: float = 1800.0, **kwargs) -> dict:
    """Run ``fn(*args, **kwargs)`` on a daemon thread; return its task dict at
    once: ``{"id", "status": "running"}`` (or ``status: "busy"`` with an error
    message when max_concurrent is reached). The outcome later appears as
    status ``"done"``/``"error"`` with ``"result"``; finished tasks are kept
    for grace_s (default 30 min) then pruned. fn must not raise for expected
    failures — return an error string instead; raises are caught and recorded
    as status "error"."""
    with _tasks_lock:
        running = sum(1 for t in _tasks.values() if t["status"] == "running")
        if running >= max_concurrent:
            return {"status": "busy", "error": f"{running} 个后台任务在跑(上限 {max_concurrent}), 稍等再试"}
        now = time.time()
        for k in [k for k, t in _tasks.items()
                  if t["status"] != "running" and now - t["finished"] > t["grace_s"]]:
            del _tasks[k]
        tid = uuid.uuid4().hex[:12]
        task = {"id": tid, "status": "running", "result": "", "started": now,
                "grace_s": grace_s, "done": threading.Event()}
        _tasks[tid] = task

    def _run():
        try:
            task["result"] = fn(*args, **kwargs)
            task["status"] = "done"
        except Exception as e:  # noqa: BLE001 — a crashed worker must still surface
            task["result"] = f"{type(e).__name__}: {e}"
            task["status"] = "error"
        finally:
            task["finished"] = time.time()
            task["done"].set()

    threading.Thread(target=_run, daemon=True, name=f"huamcp-task-{tid}").start()
    return task


def poll_task(task_id: str) -> dict:
    """Fetch a task dict from submit_task(). Unknown/expired ids come back as
    status "gone" with a human-readable result field."""
    with _tasks_lock:
        t = _tasks.get((task_id or "").strip())
    if t is None:
        return {"id": task_id, "status": "gone",
                "result": "task 不存在(结果已过保留期清理, 或 task_id 不对)"}
    return t
