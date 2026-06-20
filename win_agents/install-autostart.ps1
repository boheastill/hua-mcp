# One-time: register win-agents (:8001) to auto-start on Windows login.
# Run ONCE in an elevated PowerShell on the Windows host.
#
# Design: the code lives only in WSL (single source of truth). Windows runs it in
# place over the \\wsl.localhost path using Windows-native Python/uv. If running from
# the UNC path is flaky on your box, set $RepoOnWindows below to a local clone path.

$ErrorActionPreference = "Stop"

# Path to win_agents as seen from Windows. Adjust <distro> if not "Ubuntu".
$WinAgents = "\\wsl.localhost\Ubuntu\home\bohea\code-workspace\hua-mcp\win_agents"
# $WinAgents = "C:\hua-mcp\win_agents"   # <- uncomment if you cloned to C: instead

$RunPs1 = Join-Path $WinAgents "run.ps1"
if (-not (Test-Path $RunPs1)) { throw "run.ps1 not found at $RunPs1 — fix the path above." }

$action  = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$RunPs1`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName "hua-mcp-win-agents-8001" `
    -Action $action -Trigger $trigger -Settings $settings -Force `
    -Description "hua-mcp win-agents MCP server on :8001"

Write-Host "Registered. Start now with:  Start-ScheduledTask -TaskName hua-mcp-win-agents-8001"
Write-Host "Verify:  curl http://localhost:8001/health"
