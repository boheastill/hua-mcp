# Launch every Windows-hosted MCP (one process each). Skips _-prefixed dirs.
$ErrorActionPreference = "Stop"
Get-ChildItem -Directory $PSScriptRoot | Where-Object { $_.Name -notlike "_*" } | ForEach-Object {
    $run = Join-Path $_.FullName "run.ps1"
    if (Test-Path $run) {
        Start-Process powershell -ArgumentList "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$run`""
    }
}
