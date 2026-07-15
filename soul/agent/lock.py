"""agent.lock — single-instance guard with stale-lock takeover (spec P5).

The lock file holds the owning process's pid and a timestamp. On acquisition, if
a lock already exists we check whether that pid is still alive; if not (stale
lock, e.g. after a crash), we take it over. Liveness is checked without third-
party dependencies:

    * POSIX: ``os.kill(pid, 0)``.
    * Windows: ``OpenProcess`` via ``ctypes`` (no psutil needed).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any


class LockError(Exception):
    """Raised when the lock is held by a live process."""


def _pid_alive(pid: int) -> bool:
    """Return True if a process with ``pid`` is currently running."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _pid_alive_windows(pid)
    return _pid_alive_posix(pid)


def _pid_alive_posix(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists but owned by another user.
        return True
    return True


def _pid_alive_windows(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION, False, pid
    )
    if not handle:
        # Could not open: most commonly the process does not exist.
        return False
    try:
        exit_code = wintypes.DWORD()
        ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        if not ok:
            return False
        return exit_code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _read_lock(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


class AgentLock:
    """A pid+timestamp lock file with stale takeover.

    Usable as a context manager::

        with AgentLock(paths.agent_lock):
            run_step(...)
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._acquired = False

    def acquire(self) -> None:
        existing = _read_lock(self.path)
        if existing is not None:
            pid = int(existing.get("pid", -1))
            if pid != os.getpid() and _pid_alive(pid):
                raise LockError(
                    f"agent.lock held by live process pid={pid} "
                    f"(since {existing.get('acquired_at')})."
                )
            # Otherwise: stale (dead pid) or our own — take it over.

        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "pid": os.getpid(),
            "acquired_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        self._acquired = True

    def release(self) -> None:
        if not self._acquired:
            return
        current = _read_lock(self.path)
        # Only remove if we still own it.
        if current is not None and int(current.get("pid", -1)) == os.getpid():
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
        self._acquired = False

    def __enter__(self) -> "AgentLock":
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()
