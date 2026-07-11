# Launch every Windows-hosted MCP (one process each). Skips _-prefixed dirs.
# conhost --headless: -WindowStyle Hidden alone is ignored when Windows Terminal is the
# default terminal app, so a console window pops up at login. A headless conhost has no
# window under any default-terminal setting. Logs go to %LOCALAPPDATA%\hua-mcp\<name>\ (see run.ps1).
$ErrorActionPreference = "Stop"
Get-ChildItem -Directory $PSScriptRoot | Where-Object { $_.Name -notlike "_*" } | ForEach-Object {
    $run = Join-Path $_.FullName "run.ps1"
    if (Test-Path $run) {
        Start-Process conhost.exe -WindowStyle Hidden -ArgumentList "--headless powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$run`""
    }
}
