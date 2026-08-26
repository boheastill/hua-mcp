# hua-mcp — a fleet of MCP servers, with no central registry

**One MCP = one directory = one port.** Adding a server means copying a
template directory; removing one means deleting it. Nothing in the middle needs
editing, because every tool that manages the fleet discovers it by *scanning*
`*/*/mcp.json` rather than reading a list someone has to remember to update.

The fleet spans two hosts — Windows and WSL — and agents on either side just
connect to `localhost:<port>` without caring which machine the server actually
runs on.

*[中文版 → README.zh.md](README.zh.md)*

```bash
git clone https://github.com/boheastill/hua-mcp && cd hua-mcp
./fleet.sh validate     # every mcp.json well-formed, ports unique and in band
./fleet.sh test         # install deps + import each server (smoke)
./fleet.sh up           # start the WSL servers under PM2
./fleet.sh health       # curl every /health
```

## The contract: your server file only declares tools

Every cross-cutting concern — bind address, `/health`, bearer auth, transport
selection — lives once, in `huamcp.py`. A server is therefore just tool
declarations, and an agent editing one has very little room to get it wrong:

```python
import pathlib, sys
for _p in pathlib.Path(__file__).resolve().parents:
    if (_p / "huamcp.py").exists():
        sys.path.insert(0, str(_p)); break
import huamcp

mcp = huamcp.server(__file__)      # reads its own mcp.json: bind + /health + auth

@mcp.tool()
def my_tool(...): ...              # ← the only part that varies

if __name__ == "__main__":
    huamcp.run(mcp)                # streamable-http (--stdio for local)
```

`mcp.json` (`name` / `port` / `os` / `public` / optional `auth_env`) is a
server's **only** metadata. There is no registry file to drift out of sync.

## Design decisions worth stealing

* **Secure by default, public by opt-in.** `huamcp` binds `127.0.0.1`. Exposing
  a server means `--public` (or `HUAMCP_PUBLIC=1`), never an accidental default.
  Under WSL2 mirrored networking, `127.0.0.1` is still reachable in both
  directions between Windows and WSL — so the safe default costs the fleet
  nothing.
* **Auth is a seam, not a rewrite.** Set `auth_env` in `mcp.json` and give that
  environment variable a value: every route except `/health` now requires
  `Authorization: Bearer <token>`. Going from private to internet-facing is a
  config change, not a code change.
* **Uniform `/health`.** `{ok, mcp, os, port, public}`, identical everywhere, so
  one loop checks the whole fleet.
* **Gates, not vibes.** `validate` (keys present, ports unique and inside the
  host's band, required files exist) and `test` (install + import every server)
  both exit non-zero. `test --live` actually starts each server and curls it.
* **Pinned everything.** Python via `requirements.lock` (`uv pip compile`), Node
  via committed `package-lock.json` (`npm ci`), and for the PDF renderer a Nix
  flake pinning Chromium and the fonts — because "works on my machine" is a
  worse bug in a personal fleet than in a product, since you are the only one
  who will ever debug it.

Port bands: `win 8001–8099`, `wsl 8100+`.

## The three things that killed servers in production

These cost me real evenings. They are all fixed in the templates, and they are
the reason this repo exists as something to copy rather than notes in a file:

| Symptom | Root cause | Fix (already in the template) |
|---|---|---|
| Node/Chromium aborts with SIGABRT under the service manager, but runs fine by hand | PM2 injects `NODE_CHANNEL_FD` into children; a *grandchild* node process inherits a dead IPC fd and aborts on startup | `unset NODE_CHANNEL_FD` at the top of `run.sh` |
| A console window appears at login even with `-WindowStyle Hidden` | Windows Terminal, as the default terminal application, ignores `Hidden` | Launch through `conhost.exe --headless` |
| Service "starts then instantly dies" — but only after adding log redirection | With `$ErrorActionPreference = "Stop"`, PowerShell treats the first stderr line of a redirected native program as fatal — and uvicorn logs to stderr | Redirect via `cmd /c "... >> log 2>&1"` for long-running processes |

Debugging entry points: `pm2 logs mcp-<name>-<port>` on WSL;
`%LOCALAPPDATA%\hua-mcp\<name>\server.log` on Windows. To test the Windows
autostart chain *from* WSL, use `Start-ScheduledTask -TaskName hua-mcp-win` — a
process tree launched directly through interop gets reaped when the interop
command returns, so testing it that way gives you a false negative.

## Adding, changing, removing a server

```bash
cp -r _template wsl/myname          # or win/myname
$EDITOR wsl/myname/mcp.json         # name == directory name, port, os
$EDITOR wsl/myname/server.py        # write @mcp.tool()
uv pip compile requirements.txt -o requirements.lock
./fleet.sh validate && ./fleet.sh test
./fleet.sh up
```

Removing one is `./fleet.sh down` then `rm -rf` the directory. `fleet.sh` and
`gen_config.py` find what exists by scanning, so **no central file is ever
edited**.

## What's in the fleet here

| MCP | Port | Host | What it does |
|---|---|---|---|
| `vpn` | 8001 | Windows | Manage a local sing-box proxy: status, restart, connectivity and route tests, log tail, config read/validate/write, node switching |
| `glm-search` | 8100 | WSL | Relay to BigModel's plan-only web-search MCP: `web_search_prime` (×1.2 credits); key reused from `~/.glm/key.txt`, see OPS_NOTES §十二 |
| `identity` | 8101 | WSL | Nine checks an agent can run to work out *which model it is actually running as* — env analysis, DNS/endpoint verification, runtime and process inspection, fused into a confidence score with counter-evidence stated |
| `glmvision` | 8102 | WSL | `describe_image` — vision/OCR via Zhipu GLM vision models |
| `agy` | 8103 | WSL | `agy_ask`/`agy_quota` — delegate heavy/Google-grade work to the agy CLI |
| `ics-core` | 8104 | WSL | ICS message stream: `list_messages` `read_message` `push_message` `push_file` `manage_message` (see the [ics project](../ics/ics-mcp-server/README.md)) |
| `local-model` | 8105 | WSL | `local_ask` + `local_vision` — local LLM delegation via the lb desktop's llama-server (OpenAI-compatible; auto-discovers the live model, see the model registry) |
| `glm-reader` | 8106 | WSL | Relay to BigModel's plan-only web-reader MCP: `webReader` (URL → structured content, ×1.2 credits) |
| `glm-repo` | 8107 | WSL | Relay to BigModel's zread MCP: `search_doc` / `get_repo_structure` / `read_file` for digesting public GitHub repos (×1.2 credits) |
| `md2pdf` | 8110 | WSL | Markdown → PDF, fully offline: mermaid blocks pre-rendered to inline base64 SVG by a locally installed `mmdc` (no network, no `npx` cold start), CJK-safe fonts pinned by Nix. Exposed both as an MCP tool and as `POST /pdf` |
| `printctl` | 8120 | WSL | LAN printer control: print/scan/status discovery |
| `paper-hub` | 8121 | WSL | Physical paper tasks: `create_paper_task` etc. |
| `phone-eye` | 8122 | WSL | Agent eyes and hands on a real phone: `phone_look` (vision Q&A + UI tree), `phone_tap/swipe/type`, `phone_screenshot` — over Wi-Fi adb. Core lives in its own distributable repo; this is the fleet wrapper |
| `kimi` | 8125 | WSL | Moonshot Kimi Code subscription facade: `kimi_ask` (text delegation, K3 1M ctx, effort low/high/max) / `kimi_vision` (image fallback). Key at `~/.kimi/key.txt`; same subscription pool as dsh route kimi/k3 |

How each agent CLI (Claude Code / Codex / agy / dsh) wires up to the fleet —
see **[CLIENTS.md](CLIENTS.md)**.

Environment-specific data — server inventories, SSH keys, proxy node groups —
is kept outside this repo by design; the `vpn` server documents where it looks
without shipping any of it.

Scope: this fleet holds **personal, general-purpose** tools. Project-coupled
servers belong in their own projects.

## What this is and isn't

This is infrastructure I actually run every day, published because the shape of
it — scan-don't-register, one shared runtime, safe-by-default binding, gates
that exit non-zero — is the part worth copying. It is not a framework, it has no
plugin API, and it makes no attempt to be generic beyond two hosts and a handful
of servers. If you run more than a handful, you probably want something with a
supervisor and a service discovery story; the ideas here should still port.

## Related

* [boheastill.com/demos](https://boheastill.com/demos/?r=gh-hua-mcp) — other runnable demos
* [`wsl/md2pdf`](wsl/md2pdf) — the offline markdown→PDF renderer, usable on its own

## License

MIT — see [LICENSE](LICENSE).
