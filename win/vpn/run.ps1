# MCP launcher (Windows host). Started on boot via ../install-autostart.ps1.
# Code lives in WSL and is read over the \\wsl.localhost UNC path (single source of
# truth). The venv CANNOT live on that UNC path (uv can't build it there), so it goes
# on a native local disk under %LOCALAPPDATA%\hua-mcp\<name>\.venv.
$ErrorActionPreference = "Stop"
$src  = $PSScriptRoot
$name = Split-Path $src -Leaf
$venv = Join-Path $env:LOCALAPPDATA "hua-mcp\$name\.venv"
$py   = Join-Path $venv "Scripts\python.exe"

if (-not (Test-Path $py)) { uv venv $venv }
$req = if (Test-Path (Join-Path $src "requirements.lock")) { Join-Path $src "requirements.lock" } else { Join-Path $src "requirements.txt" }
uv pip install -q --python $py -r $req
& $py (Join-Path $src "server.py")
