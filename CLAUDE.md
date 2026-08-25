# CLAUDE.md — rules for agents working in hua-mcp

Read this first. It is the contract. Following it means you can add/edit/remove an MCP
without breaking anything. The structure is intentionally boring so a context-less
agent gets it right.

## What this repo is

A fleet of MCP servers. **One MCP = one directory = one port.** Grouped by host OS:
`win/<name>/` runs on the Windows host, `wsl/<name>/` runs in WSL. Agents reach every
server at `http://localhost:<port>/mcp` (WSL2 mirrored networking makes localhost work
both directions).

How each agent CLI (Claude Code / Codex / agy / dsh) wires up to the fleet:
see **[CLIENTS.md](CLIENTS.md)**. Ops rules and incident history: OPS_NOTES.md.

## The invariants (do not violate)

1. **A server.py only declares tools.** All plumbing (bind address, `/health`, auth,
   transport) lives in `huamcp.py`. A server is exactly:
   ```python
   import pathlib, sys
   for _p in pathlib.Path(__file__).resolve().parents:
       if (_p/"huamcp.py").exists(): sys.path.insert(0, str(_p)); break
   import huamcp
   mcp = huamcp.server(__file__)
   @mcp.tool()
   def my_tool(...): ...        # add tools here
   if __name__ == "__main__":
       huamcp.run(mcp)
   ```
2. **`mcp.json` is the only metadata.** Keys: `name` (== its directory name), `port`,
   `os` (`win`|`wsl`), `public` (bool), optional `auth_env`. There is **no central
   registry** — never create one. Tools (`fleet.sh`, `gen_config.py`) discover MCPs by
   scanning `*/*/mcp.json`.
3. **Ports:** win `8001-8099`, wsl `8100+`, unique. Don't hand-pick — use `fleet.sh new`.
4. **Secure by default.** `huamcp` binds `127.0.0.1`. Never hardcode `0.0.0.0`; public
   exposure is `--public` / `HUAMCP_PUBLIC=1` at runtime, plus a token via `auth_env`.
5. **Dependencies are per-MCP and pinned.** Each MCP has its own `requirements.txt` +
   `requirements.lock`. Never add a shared/global requirements file.
6. **`huamcp.py` is shared by every MCP.** Editing it affects all of them — change it
   only deliberately, then run `./fleet.sh test`.

## Add an MCP

```bash
./fleet.sh new wsl myname      # or: win myname  — scaffolds + assigns a free port
# edit wsl/myname/server.py  (write @mcp.tool());  add deps to requirements.txt
uv pip compile requirements.txt -o requirements.lock   # in the MCP dir
./fleet.sh validate && ./fleet.sh test                 # MUST pass
./fleet.sh sync                # wsl: start + persist + register with Claude + health
                               # (win: re-run win/install-autostart.ps1 on the Windows host)
```
`sync` treats every wsl MCP identically — nothing is special-cased per MCP. After
`./fleet.sh sync` the new MCP is running, survives reboot (once `pm2 startup` was set up
once), and is callable from Claude Code, exactly like the existing ones.

## Edit / remove an MCP

- Edit: change tools in its `server.py` / `requirements.txt`; re-run `validate` + `test`.
- Remove: `./fleet.sh down` then `rm -rf <os>/<name>` then `claude mcp remove <name> -s user`.

## Before you commit

`./fleet.sh validate` (structure) and `./fleet.sh test` (venv + import) must pass. The
pre-commit hook (`./fleet.sh install-hooks`) runs validate + Python syntax automatically.

## Don'ts

- Don't add a central registry / shared requirements / a "manager" layer.
- Don't hardcode ports, hosts, or auth in a server.py — that's `mcp.json` + `huamcp`.
- Don't put Windows-only deps (pywin32 etc.) in a `wsl/` MCP, or vice versa.
- Don't bypass `fleet.sh new` for port selection (you'll risk a collision).
- Don't "simplify away" the odd-looking guard lines in the launchers — each one fixes a
  real production kill (see README "疑难速查"): `unset NODE_CHANNEL_FD` in `run.sh`
  (PM2's IPC fd SIGABRTs any child node), `conhost --headless` in the win autostart
  chain (Windows Terminal ignores `-WindowStyle Hidden`), and `cmd /c "... >> log 2>&1"`
  in `run.ps1` (PowerShell's own stderr redirection kills the server on its first log line).
