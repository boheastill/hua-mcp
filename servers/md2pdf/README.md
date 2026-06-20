# md2pdf — Markdown → PDF (MCP + REST)

Heavy / isolated server in the hua-mcp fleet. Turns a Markdown string into a
polished, CJK-safe PDF, fully **offline**, with `` ```mermaid `` architecture
diagrams pre-rendered to inline SVG.

It lives in the `servers/` tier (not inside `wsl_agents`) on purpose: it forks a
headless **Chromium** and can be memory-hungry or hang, so it gets its **own
process and own port (8010)** — a wedged render can't take down the rest of the
fleet.

## Two faces, one process

| Face | For | Endpoint |
|------|-----|----------|
| MCP tool `md_to_pdf` | Agents (Claude on WSL / Windows, via the fleet port) | `streamable-http` on `:8010` |
| REST `POST /pdf` | The future public website endpoint (email-gated later) | `:8010/pdf` |
| REST `GET /health` | Fleet health probe | `:8010/health` |

`POST /pdf` body: `{"md": "...", "title": "...", "subtitle": "...", "author": "...", "lang": "zh"}` → returns `application/pdf`.

## MCP tool

`md_to_pdf(markdown, output_path=None, title=None, subtitle=None, author=None, lang="en", return_base64=False)`

- **Same machine** as the caller → pass `output_path`, get the file written there.
- **Cross-host** (Windows agent → WSL server, or public) → omit `output_path`; the
  PDF comes back base64-encoded (`pdf_base64`). Portable, transport-agnostic.

## Run

```bash
./run.sh                 # PM2 uses this; enters nix develop, installs deps, serves :8010
# or by hand for stdio (single local client):
nix develop -c bash -c '.venv/bin/python server.py'
```

First run installs the Python venv (`uv`) and `node_modules` (mermaid-cli). Chromium
and Noto CJK fonts come from `flake.nix` — nothing is installed system-wide.

Managed by PM2 as `mcp-md2pdf-8010` (see `../../ecosystem.config.js`).

## Auth seam

Set env `MD2PDF_TOKEN` to require `Authorization: Bearer <token>` on the REST routes.
Unset = no-op (local/dev). Going public is a config flip, not a rewrite.

## Cross-OS reachability

The fleet relies on WSL2 **mirrored networking** (`.wslconfig → networkingMode=mirrored`),
so `localhost:8010` resolves both Windows→WSL and WSL→Windows. Already enabled on this host.
