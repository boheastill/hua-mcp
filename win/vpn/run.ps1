# vpn MCP launcher (Windows host). Run on boot via ../install-autostart.ps1.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path .venv)) { uv venv .venv }
$env:VIRTUAL_ENV = Join-Path $PSScriptRoot ".venv"
$req = if (Test-Path requirements.lock) { "requirements.lock" } else { "requirements.txt" }
uv pip install -q -r $req
& (Join-Path $PSScriptRoot ".venv\Scripts\python.exe") server.py
