"""md2pdf — heavy-isolated MCP server (markdown → premium PDF).

One process, two faces:
  • MCP tool  `md_to_pdf`   — for agents (Claude on WSL / Windows, via the fleet port).
  • REST      `POST /pdf`   — for the future public website endpoint (email-gated later).
  • REST      `GET  /health`— fleet health probe.

Transport:
  default            → stdio (local single-client).
  --http / --sse     → network port 8010 (streamable-http), reachable cross-OS thanks
                       to WSL2 mirrored networking. This is the fleet-canonical mode.

Auth seam: if env MD2PDF_TOKEN is set, REST routes require `Authorization: Bearer <token>`.
When unset it is a no-op — so going public later is a config flip, not a rewrite.
"""

import os
import base64
import json
import tempfile
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from renderer import Md2Pdf

META = json.loads((Path(__file__).resolve().parent / "mcp.json").read_text(encoding="utf-8"))
PORT = int(os.environ.get("MD2PDF_PORT", META["port"]))
TOKEN = os.environ.get("MD2PDF_TOKEN")  # None => auth disabled (local/dev)
VERSION = "0.1.0"

mcp = FastMCP(META["name"], host="0.0.0.0", port=PORT)
_renderer = Md2Pdf()


def _render(md: str, *, title=None, subtitle=None, author=None, lang="en") -> bytes:
    md = (md or "").strip()
    if not md:
        raise ValueError("markdown is empty")
    tmp = Path(tempfile.mkdtemp(prefix="md2pdf_"))
    out = tmp / "out.pdf"
    try:
        _renderer.render_to_pdf(
            md, str(out), title=title, subtitle=subtitle, author=author, lang=lang
        )
        return out.read_bytes()
    finally:
        # Best-effort cleanup; never let cleanup mask a render error.
        try:
            out.unlink(missing_ok=True)
            tmp.rmdir()
        except OSError:
            pass


# --- MCP tool ----------------------------------------------------------------
@mcp.tool()
def md_to_pdf(
    markdown: str,
    output_path: str | None = None,
    title: str | None = None,
    subtitle: str | None = None,
    author: str | None = None,
    lang: str = "en",
    return_base64: bool = False,
) -> dict:
    """Render a Markdown string to a polished PDF (offline; supports ```mermaid``` diagrams).

    Args:
        markdown: The Markdown source text.
        output_path: Absolute path to write the PDF to. Only meaningful when the server
            runs on the SAME machine/filesystem as the caller. For cross-host calls,
            omit it and use return_base64 instead.
        title: Optional document title (renders a header). Omit for a bare body.
        subtitle: Optional subtitle under the title.
        author: Optional author shown in the header meta.
        lang: Document language attribute (default "en"; use "zh" for Chinese).
        return_base64: If true, include the PDF bytes base64-encoded in the result
            (portable across machines).

    Returns:
        dict with: ok, size_bytes, and either `output_path` (if written to disk) and/or
        `pdf_base64` (if requested).
    """
    pdf = _render(markdown, title=title, subtitle=subtitle, author=author, lang=lang)
    result: dict = {"ok": True, "size_bytes": len(pdf)}
    if output_path:
        p = Path(output_path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(pdf)
        result["output_path"] = str(p)
    if return_base64 or not output_path:
        result["pdf_base64"] = base64.b64encode(pdf).decode("ascii")
    return result


# --- REST faces (for the future public website + health) ---------------------
def _check_auth(request) -> bool:
    if not TOKEN:
        return True
    auth = request.headers.get("authorization", "")
    return auth == f"Bearer {TOKEN}"


@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    from starlette.responses import JSONResponse

    return JSONResponse({"ok": True, "service": "md2pdf", "version": VERSION})


@mcp.custom_route("/pdf", methods=["POST"])
async def pdf_endpoint(request):
    from starlette.responses import JSONResponse, Response

    if not _check_auth(request):
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"detail": "invalid JSON body"}, status_code=400)

    md = (body or {}).get("md", "")
    try:
        pdf = _render(
            md,
            title=body.get("title"),
            subtitle=body.get("subtitle"),
            author=body.get("author"),
            lang=body.get("lang", "en"),
        )
    except ValueError as e:
        return JSONResponse({"detail": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"detail": f"render failed: {e}"}, status_code=500)

    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="document.pdf"'},
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="md2pdf MCP server")
    parser.add_argument("--http", action="store_true", help=f"Run streamable-http on :{PORT}")
    parser.add_argument("--sse", action="store_true", help=f"Run legacy SSE on :{PORT}")
    args = parser.parse_args()

    if args.sse:
        mcp.run(transport="sse")
    elif args.http:
        mcp.run(transport="streamable-http")
    else:
        mcp.run()  # stdio
