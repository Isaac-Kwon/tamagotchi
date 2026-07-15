# Auto-restart wrapper for the API server (spec P5: process isolation).
#
# Runs run_web.py and restarts it after an exponential backoff on a non-zero
# exit. The web server is independent of the agent loop, so a crash here never
# affects the agent (and vice versa).
#
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\start_web.ps1

param(
    [string]$Python = ".\.venv\Scripts\python.exe",
    [string]$Config = "config.json"
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location (Split-Path -Parent $scriptRoot)

$backoff = 1
$maxBackoff = 300

while ($true) {
    Write-Host "[start_web] launching API server..."
    & $Python run_web.py --config $Config
    $code = $LASTEXITCODE

    if ($code -eq 0) {
        Write-Host "[start_web] web server exited cleanly (0). Stopping wrapper."
        break
    }

    Write-Host "[start_web] web server exited with code $code. Restarting in $backoff s..."
    Start-Sleep -Seconds $backoff
    $backoff = [Math]::Min($backoff * 2, $maxBackoff)
}
