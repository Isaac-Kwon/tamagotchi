# Launches the agent loop AND the web server together, each in its own
# PowerShell window, by delegating to the existing auto-restart wrappers
# (start_agent.ps1 / start_web.ps1). Closing this script does not stop them —
# stop each one with Ctrl-C in its own window.
#
# The agent.lock / port bind refuse duplicate instances, so if one of the two
# is already running elsewhere, only the other will actually start (the
# duplicate's wrapper will keep retrying — close that window).
#
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\start_all.ps1

param(
    [string]$Config = "config.json",
    [switch]$NoWsl
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

function Start-Wrapper([string]$label, [string]$scriptName) {
    $psArgs = @(
        "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $scriptRoot $scriptName),
        "-Config", $Config
    )
    if ($NoWsl) { $psArgs += "-NoWsl" }
    Start-Process powershell -ArgumentList $psArgs
    Write-Host "[start_all] launched $label ($scriptName) in a new window."
}

Start-Wrapper "agent loop" "start_agent.ps1"
Start-Wrapper "web server" "start_web.ps1"
Write-Host "[start_all] both windows are up. Web UI: http://127.0.0.1:8000/"
