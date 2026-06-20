"""identity MCP — detect the real running model / provider / runtime (9 checks)."""
import pathlib
import sys

for _p in pathlib.Path(__file__).resolve().parents:
    if (_p / "huamcp.py").exists():
        sys.path.insert(0, str(_p))
        break
import huamcp  # noqa: E402

import checker  # noqa: E402

mcp = huamcp.server(__file__)

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

if __name__ == "__main__":
    huamcp.run(mcp)
