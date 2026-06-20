"""WSL agent server (:8002) — Linux-native tools.

Thin by design: config comes from ../registry.json, tools auto-load from ./tools/
(each tool module defines `register(mcp)`). To add a tool, drop a file in tools/.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "shared"))
import fleet  # noqa: E402

if __name__ == "__main__":
    fleet.serve("wsl-agents")
