# One-time: register the Windows-hosted MCPs to auto-start on login.
# Run ONCE in an elevated PowerShell on the Windows host.
#
# Code lives only in WSL (single source of truth); Windows runs it in place over the
# \\wsl.localhost path. If that's flaky on your box, clone to C: and fix $WinDir.

$ErrorActionPreference = "Stop"

# Path to this win/ dir as seen from Windows. Adjust <distro> if not "Ubuntu".
$WinDir = "\\wsl.localhost\Ubuntu\home\bohea\code-workspace\hua-mcp\win"
# $WinDir = "C:\hua-mcp\win"   # <- uncomment if you cloned to C: instead

$StartAll = Join-Path $WinDir "start-all.ps1"
if (-not (Test-Path $StartAll)) { throw "start-all.ps1 not found at $StartAll — fix the path above." }

$action  = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$StartAll`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName "hua-mcp-win" `
    -Action $action -Trigger $trigger -Settings $settings -Force `
    -Description "hua-mcp Windows-hosted MCP servers (win/*)"

Write-Host "Registered. Start now with:  Start-ScheduledTask -TaskName hua-mcp-win"
Write-Host "Verify each win MCP, e.g.:    curl http://localhost:8001/health"
