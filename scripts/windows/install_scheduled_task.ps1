# install_scheduled_task.ps1
#
# Registers a Windows Scheduled Task that starts run_bot_forever.ps1
# automatically at logon and keeps it running in the background, so the
# bot survives reboots and comes back on its own if it crashes.
#
# Run from an elevated (Administrator) PowerShell prompt:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
#   .\install_scheduled_task.ps1
#
# To remove it later:
#   Unregister-ScheduledTask -TaskName "GogonBot" -Confirm:$false

$ErrorActionPreference = 'Stop'

$TaskName = "GogonBot"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$SupervisorScript = Join-Path $PSScriptRoot "run_bot_forever.ps1"

if (-not (Test-Path $SupervisorScript)) {
    throw "Could not find $SupervisorScript"
}

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$SupervisorScript`"" `
    -WorkingDirectory $RepoRoot

# Starts at logon for the current user, and also immediately if the task
# is (re)registered while the user is already logged in.
$Trigger = New-ScheduledTaskTrigger -AtLogOn

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)  # never time out / auto-kill it

$Principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Keeps the gogon Polymarket bot running, auto-restarting on crash." `
    -Force | Out-Null

Write-Host "Scheduled task '$TaskName' installed." -ForegroundColor Green
Write-Host "It will start automatically next time you log in." -ForegroundColor Green
Write-Host ""
Write-Host "Start it right now:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Check status:        Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo"
Write-Host "Stop it:             Stop-ScheduledTask -TaskName '$TaskName'"
Write-Host "Remove it:           Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"

Write-Host ""
$startNow = Read-Host "Start the task now? (y/N)"
if ($startNow -eq "y" -or $startNow -eq "Y") {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Started. Tail logs\supervisor.log and logs\bot.log to watch it." -ForegroundColor Green
}
