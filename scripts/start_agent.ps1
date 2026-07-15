# Auto-restart wrapper for the agent loop (spec P5: loop-crash resilience).
#
# Runs run_agent.py and, if it exits non-zero (a crash), restarts it after an
# exponential backoff (capped). A clean exit (code 0, e.g. Ctrl-C) stops the
# wrapper. The agent.lock refuses a second live instance, so this never
# double-starts.
#
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\start_agent.ps1

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
    Write-Host "[start_agent] launching agent loop..."
    & $Python run_agent.py --config $Config
    $code = $LASTEXITCODE

    if ($code -eq 0) {
        Write-Host "[start_agent] agent exited cleanly (0). Stopping wrapper."
        break
    }

    Write-Host "[start_agent] agent exited with code $code. Restarting in $backoff s..."
    Start-Sleep -Seconds $backoff
    $backoff = [Math]::Min($backoff * 2, $maxBackoff)
}
