"""Windows agent server (:8001) — Windows-only tools (clipboard, GUI, services).

Thin by design: config from ../registry.json, tools auto-load from ./tools/.
Runs on the Windows host (Python + uv), reachable from WSL agents via mirrored
networking on localhost:8001.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "shared"))
import fleet  # noqa: E402

if __name__ == "__main__":
    fleet.serve("win-agents")
