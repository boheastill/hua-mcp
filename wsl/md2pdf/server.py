"""md2pdf -- markdown to premium PDF (offline, mermaid-capable).

Tool: md_to_pdf(markdown, output_path?, title?, subtitle?, author?, lang?, return_base64?)
REST: POST /pdf  body: {"md": "...", "title": "...", "lang": "en"}  returns PDF bytes.
Port: 8110. Auth: MD2PDF_TOKEN env var (optional). Health: GET /health.
"""
import base64
import pathlib
import sys
import tempfile
from pathlib import Path

for _p in pathlib.Path(__file__).resolve().parents:
    if (_p / "huamcp.py").exists():
        sys.path.insert(0, str(_p))
        break
import huamcp  # noqa: E402

from renderer import Md2Pdf  # noqa: E402

mcp = huamcp.server(__file__)
_renderer = Md2Pdf()


def _render(md: str, *, title=None, subtitle=None, author=None, lang="en") -> bytes:
    md = (md or "").strip()
    if not md:
        raise ValueError("markdown is empty")
    tmp = Path(tempfile.mkdtemp(prefix="md2pdf_"))
    out = tmp / "out.pdf"
    try:
        _renderer.render_to_pdf(md, str(out), title=title, subtitle=subtitle, author=author, lang=lang)
        return out.read_bytes()
    finally:
        # Best-effort cleanup; never let cleanup mask a render error.
        try:
            out.unlink(missing_ok=True)
            tmp.rmdir()
        except OSError:
            pass


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


@mcp.custom_route("/pdf", methods=["POST"])
async def pdf_endpoint(request):
    # Auth (when a token is configured) is enforced uniformly by huamcp middleware.
    from starlette.responses import JSONResponse, Response

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"detail": "invalid JSON body"}, status_code=400)
    try:
        pdf = _render(
            (body or {}).get("md") or (body or {}).get("markdown", ""),
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
    huamcp.run(mcp)
