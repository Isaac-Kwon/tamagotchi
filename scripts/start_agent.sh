#!/usr/bin/env bash
# Auto-restart wrapper for the agent loop (spec P5: loop-crash resilience).
#
# Runs run_agent.py and, if it exits non-zero (a crash), restarts it after an
# exponential backoff (capped). A clean exit (code 0, e.g. Ctrl-C) stops the
# wrapper. The agent.lock refuses a second live instance, so this never
# double-starts.
#
# Native-Linux counterpart of start_agent.ps1 (no WSL indirection). Picks the
# first available venv: .venv-wsl then .venv; override with --venv <path> or
# the VENV env var.
#
# Usage:  scripts/start_agent.sh [--config config.json] [--venv .venv-wsl]

set -uo pipefail

CONFIG="config.json"
VENV="${VENV:-}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --config) CONFIG="$2"; shift 2 ;;
        --venv)   VENV="$2"; shift 2 ;;
        *) echo "[start_agent] unknown arg: $1" >&2; exit 2 ;;
    esac
done

scriptRoot="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repoRoot="$(dirname "$scriptRoot")"
cd "$repoRoot"

if [[ -z "$VENV" ]]; then
    if [[ -x ".venv-wsl/bin/python" ]]; then VENV=".venv-wsl"
    elif [[ -x ".venv/bin/python" ]]; then VENV=".venv"
    else echo "[start_agent] no venv found (.venv-wsl or .venv)" >&2; exit 1; fi
fi
PY="$VENV/bin/python"

backoff=1
maxBackoff=300

while true; do
    echo "[start_agent] launching agent loop ($PY)..."
    "$PY" run_agent.py --config "$CONFIG"
    code=$?

    if [[ $code -eq 0 ]]; then
        echo "[start_agent] agent exited cleanly (0). Stopping wrapper."
        break
    fi

    echo "[start_agent] agent exited with code $code. Restarting in ${backoff}s..."
    sleep "$backoff"
    backoff=$(( backoff * 2 ))
    if [[ $backoff -gt $maxBackoff ]]; then backoff=$maxBackoff; fi
done
