# Auto-restart wrapper for the agent loop (spec P5: loop-crash resilience).
#
# Runs run_agent.py and, if it exits non-zero (a crash), restarts it after an
# exponential backoff (capped). A clean exit (code 0, e.g. Ctrl-C) stops the
# wrapper. The agent.lock refuses a second live instance, so this never
# double-starts.
#
# Python runs on WSL by default (project rule); pass -NoWsl to force the
# Windows venv instead.
#
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\start_agent.ps1

param(
    [string]$Config = "config.json",
    [switch]$NoWsl
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptRoot
Set-Location $repoRoot

# /mnt/<drive>/<path> form of the repo root, for wsl invocations
$drive = $repoRoot.Substring(0, 1).ToLower()
$wslRoot = "/mnt/$drive" + $repoRoot.Substring(2).Replace("\", "/")

$useWsl = (-not $NoWsl) -and (Get-Command wsl -ErrorAction SilentlyContinue) -and (Test-Path ".venv-wsl")

$backoff = 1
$maxBackoff = 300

while ($true) {
    if ($useWsl) {
        Write-Host "[start_agent] launching agent loop (WSL)..."
        wsl -- bash -lc "cd '$wslRoot' && .venv-wsl/bin/python run_agent.py --config '$Config'"
    } else {
        Write-Host "[start_agent] launching agent loop (Windows venv)..."
        & ".\.venv\Scripts\python.exe" run_agent.py --config $Config
    }
    $code = $LASTEXITCODE

    if ($code -eq 0) {
        Write-Host "[start_agent] agent exited cleanly (0). Stopping wrapper."
        break
    }

    Write-Host "[start_agent] agent exited with code $code. Restarting in $backoff s..."
    Start-Sleep -Seconds $backoff
    $backoff = [Math]::Min($backoff * 2, $maxBackoff)
}
