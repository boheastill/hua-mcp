# MCP launcher (Windows host). Started on boot via win/install-autostart.ps1.
# Code stays in WSL (read over \\wsl.localhost UNC); the venv goes on a native local
# disk under %LOCALAPPDATA%\hua-mcp\<name>\.venv (uv can't build a venv on the UNC path).
$ErrorActionPreference = "Stop"
$src  = $PSScriptRoot
$name = Split-Path $src -Leaf
$venv = Join-Path $env:LOCALAPPDATA "hua-mcp\$name\.venv"
$py   = Join-Path $venv "Scripts\python.exe"

if (-not (Test-Path $py)) { uv venv $venv }
$req = if (Test-Path (Join-Path $src "requirements.lock")) { Join-Path $src "requirements.lock" } else { Join-Path $src "requirements.txt" }
uv pip install -q --python $py -r $req
& $py (Join-Path $src "server.py")
