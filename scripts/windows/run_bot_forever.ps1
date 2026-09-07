# run_bot_forever.ps1
#
# Supervisor loop for the gogon bot: runs `python -m bot.main` and, if it
# ever exits (crash, unhandled exception, network blip), waits a bit and
# restarts it automatically. Intended to be launched by the Windows
# Scheduled Task set up in install_scheduled_task.ps1, but you can also
# just run it directly in a terminal to keep the bot alive for this
# session.
#
# All supervisor activity (start/stop/restart events) is appended to
# logs\supervisor.log. The bot's own logging still goes to logs\bot.log
# as usual (see bot/logger.py).

$ErrorActionPreference = 'Continue'

# Resolve paths relative to the repo root (this script lives in scripts\windows\).
$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $RepoRoot

$LogDir = Join-Path $RepoRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$SupervisorLog = Join-Path $LogDir "supervisor.log"

$VenvPython = Join-Path $RepoRoot "venv\Scripts\python.exe"
$Python = if (Test-Path $VenvPython) { $VenvPython } else { "python" }

function Write-Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Write-Host $line
    Add-Content -Path $SupervisorLog -Value $line
}

Write-Log "Supervisor starting. Using interpreter: $Python"

$backoffSeconds = 5
$maxBackoffSeconds = 300

while ($true) {
    Write-Log "Launching bot: $Python -m bot.main"
    $start = Get-Date

    & $Python -m bot.main
    $exitCode = $LASTEXITCODE

    $ranFor = (Get-Date) - $start
    Write-Log "Bot exited with code $exitCode after $($ranFor.ToString('hh\:mm\:ss'))."

    if ($ranFor.TotalSeconds -gt 60) {
        # It ran for a while before dying, so reset the backoff.
        $backoffSeconds = 5
    } else {
        # Crashing immediately, over and over -> back off so we don't
        # hammer the API or spin the CPU.
        $backoffSeconds = [Math]::Min($backoffSeconds * 2, $maxBackoffSeconds)
    }

    Write-Log "Restarting in $backoffSeconds seconds... (Ctrl+C to stop the supervisor)"
    Start-Sleep -Seconds $backoffSeconds
}
