"""identity MCP — detect the real running model / provider / runtime.

Self-contained: reads its own mcp.json for name+port, registers the checks from
checker.py, serves streamable-http (or stdio with --stdio).
"""
import json
import pathlib
import sys

from mcp.server.fastmcp import FastMCP

import checker

HERE = pathlib.Path(__file__).resolve().parent
META = json.loads((HERE / "mcp.json").read_text(encoding="utf-8"))

mcp = FastMCP(META["name"], host="0.0.0.0", port=META["port"])

for _fn in (
    checker.check_model_identity,
    checker.check_runtime_environment,
    checker.check_api_connectivity,
    checker.get_model_config,
    checker.analyze_model_characteristics,
    checker.verify_api_endpoint,
    checker.check_network_connections,
    checker.check_process_info,
    checker.comprehensive_identity_check,
):
    mcp.tool()(_fn)


@mcp.custom_route("/health", methods=["GET"])
async def _health(request):
    from starlette.responses import JSONResponse

    return JSONResponse({"ok": True, "mcp": META["name"], "os": META["os"], "port": META["port"]})


if __name__ == "__main__":
    mcp.run() if "--stdio" in sys.argv else mcp.run(transport="streamable-http")
