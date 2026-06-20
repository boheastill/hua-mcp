# One-time: register the Windows-hosted MCPs to auto-start on login.
# Run ONCE in an elevated PowerShell on the Windows host.
#
# Code lives only in WSL (single source of truth); Windows runs it in place over the
# \\wsl.localhost path. If that's flaky on your box, clone to C: and fix $WinDir.

$ErrorActionPreference = "Stop"

# Self-elevate: registering a scheduled task needs admin. If not elevated, relaunch
# this script as admin (UAC prompt) and exit the non-elevated instance.
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "Not elevated — relaunching as admin (accept the UAC prompt)…"
    Start-Process powershell.exe -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

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

Start-ScheduledTask -TaskName "hua-mcp-win"
Write-Host "Registered AND started. It will also auto-start at every login."
Write-Host "Verify (give it ~15s):  curl.exe http://localhost:8001/health"
