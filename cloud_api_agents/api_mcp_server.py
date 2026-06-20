"""Cloud API agent server (:8003) — pure network calls (no local env deps).

Thin by design: config from ../registry.json, tools auto-load from ./tools/.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "shared"))
import fleet  # noqa: E402

if __name__ == "__main__":
    fleet.serve("cloud-api")
