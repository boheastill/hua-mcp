# Windows agent server launcher (:8001). Run on the Windows host.
# One-time + every boot via Task Scheduler (see install-autostart.ps1).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path .venv)) { uv venv .venv }
$env:VIRTUAL_ENV = Join-Path $PSScriptRoot ".venv"
uv pip install -q -r requirements.txt
& (Join-Path $PSScriptRoot ".venv\Scripts\python.exe") win_mcp_server.py --http
