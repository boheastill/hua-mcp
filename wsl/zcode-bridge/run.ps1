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
# Headless launch (no console window) -> logs must go to a file or they're lost.
# Redirect via cmd /c, NOT PowerShell (*>>): under ErrorActionPreference=Stop, PS turns
# the first redirected stderr line (uvicorn logs to stderr) into a terminating error
# and kills the server.
$log = Join-Path $env:LOCALAPPDATA "hua-mcp\$name\server.log"
$env:PYTHONUNBUFFERED = "1"
Add-Content $log "[$(Get-Date -Format s)] run.ps1: launching server.py"
cmd /c "`"$py`" `"$(Join-Path $src 'server.py')`" >> `"$log`" 2>&1"
Add-Content $log "[$(Get-Date -Format s)] run.ps1: server.py exited (code=$LASTEXITCODE)"
