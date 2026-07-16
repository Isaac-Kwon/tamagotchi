#!/usr/bin/env bash
# Launches the agent loop AND the web server together (native-Linux counterpart
# of start_all.ps1), by delegating to the existing auto-restart wrappers
# (start_agent.sh / start_web.sh). There is no portable "new terminal window"
# on Linux, so instead both wrappers run as background jobs of this script and
# their output is interleaved here; Ctrl-C stops both.
#
# Each wrapper is launched in its own process group (setsid) so that Ctrl-C
# reaches this script alone, which then tears down both groups (wrapper +
# python child) cleanly.
#
# The agent.lock / port bind refuse duplicate instances, so if one of the two
# is already running elsewhere, only the other will actually start (the
# duplicate's wrapper will keep retrying).
#
# Usage:  scripts/start_all.sh [--config config.json] [--venv .venv-wsl]

set -uo pipefail

scriptRoot="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# forward all args (--config / --venv) verbatim to both wrappers
setsid "$scriptRoot/start_agent.sh" "$@" &
agent_pid=$!
echo "[start_all] launched agent loop (start_agent.sh, pgid $agent_pid)."

setsid "$scriptRoot/start_web.sh" "$@" &
web_pid=$!
echo "[start_all] launched web server (start_web.sh, pgid $web_pid)."

echo "[start_all] both wrappers are up. Web UI: http://127.0.0.1:8000/"
echo "[start_all] Ctrl-C to stop both."

cleanup() {
    echo ""
    echo "[start_all] stopping both wrappers..."
    kill -TERM "-$agent_pid" "-$web_pid" 2>/dev/null || true
    wait 2>/dev/null || true
}
trap cleanup INT TERM

wait
