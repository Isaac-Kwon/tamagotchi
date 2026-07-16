"""Advisory file locks for cross-process coordination of append-only files.

A tiny, best-effort advisory lock built on ``O_CREAT | O_EXCL``. It is used to
serialize the brief critical sections where one process appends to (or drains)
a shared append-only file while another may be appending concurrently. It is
*advisory*: it blocks only cooperating writers that use the same lock path, and
it deliberately proceeds without the lock rather than hang if it cannot acquire
it in time (a stale lock from a crashed writer is stolen after ``stale``).
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any


class AdvisoryFileLock:
    """A tiny advisory lock (O_EXCL create). Blocks briefly, then steals stale."""

    def __init__(self, path: Path, *, timeout: float = 5.0, stale: float = 30.0) -> None:
        self.path = path
        self.timeout = timeout
        self.stale = stale
        self._fd: int | None = None

    def __enter__(self) -> "AdvisoryFileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self._fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self._fd, str(os.getpid()).encode("ascii"))
                return self
            except FileExistsError:
                # Steal a stale lock left by a crashed writer.
                try:
                    age = time.time() - self.path.stat().st_mtime
                    if age > self.stale:
                        self.path.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    # Best-effort: proceed without the lock rather than hang.
                    return self
                time.sleep(0.02)

    def __exit__(self, *exc: Any) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        self.path.unlink(missing_ok=True)
