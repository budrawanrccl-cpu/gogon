# keep_awake.ps1
#
# Configures this Windows laptop's power plan so it never sleeps while
# plugged in (AC power) and never sleeps because the lid is closed while
# plugged in. Battery-power behavior is left untouched on purpose, so the
# laptop still sleeps normally when unplugged.
#
# Run from an elevated (Administrator) PowerShell prompt:
#   Right-click PowerShell -> "Run as administrator", then:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
#   .\keep_awake.ps1
#
# Safe to re-run any time.

$ErrorActionPreference = 'Stop'

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Admin)) {
    Write-Warning "Not running as Administrator. Sleep/display timeouts will still be set, but the lid-close action may fail to change. Re-run elevated for full effect."
}

Write-Host "Setting AC (plugged-in) power behavior: never sleep, never turn off display..." -ForegroundColor Cyan

# Never sleep / never turn off display while plugged in (AC = -ac settings).
# Battery (-dc) settings are intentionally left alone.
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /change monitor-timeout-ac 0

try {
    # SUB_BUTTONS / LIDACTION = what happens when the lid closes.
    # 0 = do nothing. Only affects AC (plugged-in) behavior.
    powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0
    powercfg /setactive SCHEME_CURRENT
    Write-Host "Lid-close action (while plugged in) set to 'do nothing'." -ForegroundColor Green
} catch {
    Write-Warning "Could not change lid-close action (needs Administrator). Sleep timeouts above are still applied."
}

Write-Host ""
Write-Host "Done. While the laptop is PLUGGED IN, it will no longer sleep, dim off, or sleep on lid close." -ForegroundColor Green
Write-Host "It still sleeps normally on battery, so keep the charger connected for the bot to run 24/7." -ForegroundColor Yellow
