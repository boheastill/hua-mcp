# MCP launcher (Windows host). Started on boot via ../install-autostart.ps1.
# Code lives in WSL and is read over the \\wsl.localhost UNC path (single source of
# truth). The venv CANNOT live on that UNC path (uv can't build it there), so it goes
# on a native local disk under %LOCALAPPDATA%\hua-mcp\<name>\.venv.
#
# WSL reachability guard: if WSL is down, the UNC path is unreachable and the MCP
# would fail to import. This script checks before launching and retries with backoff.
$ErrorActionPreference = "Stop"
$src  = $PSScriptRoot
$name = Split-Path $src -Leaf
$venv = Join-Path $env:LOCALAPPDATA "hua-mcp\$name\.venv"
$py   = Join-Path $venv "Scripts\python.exe"

# WSL reachability guard
$maxAttempts = 5
for ($i = 1; $i -le $maxAttempts; $i++) {
    if (Test-Path (Join-Path $src "server.py")) {
        break
    }
    if ($i -eq $maxAttempts) {
        Write-Error "WSL unreachable after $maxAttempts attempts. Aborting $name MCP."
        exit 1
    }
    Write-Host "[$name] WSL unreachable (attempt $i/$maxAttempts), retrying in 5s..."
    Start-Sleep -Seconds 5
}

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
