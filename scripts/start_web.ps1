# Auto-restart wrapper for the API server (spec P5: process isolation).
#
# Runs run_web.py and restarts it after an exponential backoff on a non-zero
# exit. The web server is independent of the agent loop, so a crash here never
# affects the agent (and vice versa).
#
# Python runs on WSL by default (project rule); pass -NoWsl to force the
# Windows venv instead.
#
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\start_web.ps1

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
        Write-Host "[start_web] launching API server (WSL)..."
        wsl -- bash -lc "cd '$wslRoot' && .venv-wsl/bin/python run_web.py --config '$Config'"
    } else {
        Write-Host "[start_web] launching API server (Windows venv)..."
        & ".\.venv\Scripts\python.exe" run_web.py --config $Config
    }
    $code = $LASTEXITCODE

    if ($code -eq 0) {
        Write-Host "[start_web] web server exited cleanly (0). Stopping wrapper."
        break
    }

    Write-Host "[start_web] web server exited with code $code. Restarting in $backoff s..."
    Start-Sleep -Seconds $backoff
    $backoff = [Math]::Min($backoff * 2, $maxBackoff)
}
