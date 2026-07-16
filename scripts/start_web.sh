#!/usr/bin/env bash
# Auto-restart wrapper for the API server (spec P5: process isolation).
#
# Runs run_web.py and restarts it after an exponential backoff on a non-zero
# exit. The web server is independent of the agent loop, so a crash here never
# affects the agent (and vice versa).
#
# Native-Linux counterpart of start_web.ps1 (no WSL indirection). Picks the
# first available venv: .venv-wsl then .venv; override with --venv <path> or
# the VENV env var.
#
# Usage:  scripts/start_web.sh [--config config.json] [--venv .venv-wsl]

set -uo pipefail

CONFIG="config.json"
VENV="${VENV:-}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --config) CONFIG="$2"; shift 2 ;;
        --venv)   VENV="$2"; shift 2 ;;
        *) echo "[start_web] unknown arg: $1" >&2; exit 2 ;;
    esac
done

scriptRoot="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repoRoot="$(dirname "$scriptRoot")"
cd "$repoRoot"

if [[ -z "$VENV" ]]; then
    if [[ -x ".venv-wsl/bin/python" ]]; then VENV=".venv-wsl"
    elif [[ -x ".venv/bin/python" ]]; then VENV=".venv"
    else echo "[start_web] no venv found (.venv-wsl or .venv)" >&2; exit 1; fi
fi
PY="$VENV/bin/python"

backoff=1
maxBackoff=300

while true; do
    echo "[start_web] launching API server ($PY)..."
    "$PY" run_web.py --config "$CONFIG"
    code=$?

    if [[ $code -eq 0 ]]; then
        echo "[start_web] web server exited cleanly (0). Stopping wrapper."
        break
    fi

    echo "[start_web] web server exited with code $code. Restarting in ${backoff}s..."
    sleep "$backoff"
    backoff=$(( backoff * 2 ))
    if [[ $backoff -gt $maxBackoff ]]; then backoff=$maxBackoff; fi
done
