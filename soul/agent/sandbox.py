"""Isolation backend ladder for running code snippets (spec P3).

``code_experiment`` (and, later, self-authored skills) run untrusted Python
through here. The backend is chosen by a ladder, best isolation first:

    1. **Linux native** (no daemon needed): ``bwrap`` (bubblewrap) with
       ``--unshare-all --die-with-parent``; if bwrap is unavailable, an
       ``unshare --user --net --pid --map-root-user`` fallback.
    2. **Docker** (when ``docker info`` succeeds): ``--network none`` plus
       ``--memory`` / ``--pids-limit`` — the only strong isolation on Windows.
    3. **plain subprocess** (final fallback): cwd pinned to ``data/sandbox`` with
       a minimal environment and a timeout. This is **NOT** isolation and the
       code says so honestly (startup log + journal ``sandbox_backend``).

Common to every backend: a timeout (``sandbox.timeout_seconds``, default 10s)
and captured stdout/stderr. The selected backend is returned so it can be
recorded in the startup log and the journal ``sandbox_backend`` field.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Backend identifiers recorded in the journal / startup log.
BACKEND_BWRAP = "bwrap"
BACKEND_UNSHARE = "unshare"
BACKEND_DOCKER = "docker"
BACKEND_SUBPROCESS = "subprocess"

# Docker image used for the strong-isolation path (small, ships python3).
DOCKER_IMAGE = "python:3-slim"


@dataclass
class SandboxResult:
    """Outcome of running a snippet in the sandbox."""

    backend: str
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool
    isolated: bool  # False for the plain-subprocess fallback (honest flag)

    def as_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
            "isolated": self.isolated,
        }


# --------------------------------------------------------------------------- #
# Backend detection
# --------------------------------------------------------------------------- #
def _has(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _docker_available() -> bool:
    """True when ``docker info`` succeeds (daemon reachable)."""
    if not _has("docker"):
        return False
    try:
        proc = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def select_backend(requested: str = "auto") -> str:
    """Resolve the concrete backend to use for the current host.

    ``requested`` may pin a specific backend; ``"auto"`` walks the ladder.
    """
    if requested and requested != "auto":
        return requested

    if sys.platform.startswith("linux"):
        if _has("bwrap"):
            return BACKEND_BWRAP
        if _has("unshare"):
            return BACKEND_UNSHARE
    if _docker_available():
        return BACKEND_DOCKER
    return BACKEND_SUBPROCESS


def backend_is_isolated(backend: str) -> bool:
    return backend in (BACKEND_BWRAP, BACKEND_UNSHARE, BACKEND_DOCKER)


def describe_backend(backend: str) -> str:
    """Human-readable one-liner for the startup log (honest about isolation)."""
    if backend == BACKEND_BWRAP:
        return "bwrap namespace isolation (network/PID/mount unshared)"
    if backend == BACKEND_UNSHARE:
        return "unshare namespace isolation (network/PID unshared)"
    if backend == BACKEND_DOCKER:
        return "docker container isolation (--network none, memory/pids limited)"
    return "plain subprocess — NOT isolated (no strong sandbox available)"


# --------------------------------------------------------------------------- #
# Command construction per backend
# --------------------------------------------------------------------------- #
def _minimal_env() -> dict[str, str]:
    """A deliberately sparse environment for the subprocess fallback."""
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if sys.platform == "win32":
        # A few vars Windows' Python needs to import the stdlib cleanly.
        for key in ("SYSTEMROOT", "SYSTEMDRIVE", "TEMP", "TMP", "PATHEXT"):
            if key in os.environ:
                env[key] = os.environ[key]
    return env


def _build_command(
    backend: str, script_path: Path, work_dir: Path, *, interactive: bool = False
) -> list[str]:
    py = sys.executable or "python3"
    if backend == BACKEND_BWRAP:
        return [
            "bwrap",
            "--unshare-all",
            "--die-with-parent",
            "--ro-bind", "/usr", "/usr",
            "--ro-bind", "/bin", "/bin",
            "--ro-bind", "/lib", "/lib",
            "--ro-bind", "/lib64", "/lib64",
            "--bind", str(work_dir), "/work",
            "--chdir", "/work",
            "--dev", "/dev",
            "--proc", "/proc",
            "python3", str(script_path.name),
        ]
    if backend == BACKEND_UNSHARE:
        return [
            "unshare", "--user", "--net", "--pid", "--map-root-user", "--fork",
            "python3", str(script_path),
        ]
    if backend == BACKEND_DOCKER:
        return [
            "docker", "run", "--rm",
            *(["-i"] if interactive else []),
            "--network", "none",
            "--memory", "256m",
            "--pids-limit", "128",
            "--cpus", "1",
            "-v", f"{work_dir}:/work:rw",
            "-w", "/work",
            DOCKER_IMAGE,
            "python3", str(script_path.name),
        ]
    # Plain subprocess fallback.
    return [py, str(script_path)]


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def run_python(
    code: str,
    *,
    work_dir: str | Path,
    timeout_seconds: int = 10,
    backend: str = "auto",
    stdin: str | None = None,
) -> SandboxResult:
    """Run a Python ``code`` snippet through the isolation ladder.

    ``work_dir`` is the cwd (``data/sandbox``); it is created if needed. The
    snippet is written to a temp file inside it and executed by the selected
    backend. ``stdin`` (if given) is fed to the process' standard input — this
    is how :mod:`soul.agent.skill_runner` passes a skill its params as JSON. Any
    timeout or crash is captured, never raised — a failed experiment (or skill)
    is data, not a loop-killing error.
    """
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    chosen = select_backend(backend)

    script = work / "_experiment.py"
    script.write_text(code, encoding="utf-8")

    cmd = _build_command(chosen, script, work, interactive=stdin is not None)
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(work),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=_minimal_env(),
            input=stdin,
        )
        return SandboxResult(
            backend=chosen,
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            timed_out=False,
            isolated=backend_is_isolated(chosen),
        )
    except subprocess.TimeoutExpired as exc:
        return SandboxResult(
            backend=chosen,
            returncode=None,
            stdout=exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or ""),
            stderr=(exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or ""))
            + f"\n[sandbox] timed out after {timeout_seconds}s",
            timed_out=True,
            isolated=backend_is_isolated(chosen),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return SandboxResult(
            backend=chosen,
            returncode=None,
            stdout="",
            stderr=f"[sandbox] failed to run ({chosen}): {exc}",
            timed_out=False,
            isolated=backend_is_isolated(chosen),
        )
    finally:
        try:
            script.unlink(missing_ok=True)
        except OSError:
            pass
