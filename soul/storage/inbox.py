"""Observer inbox — pending -> delivered queue (spec P4/P5).

Observers (the web UI, in a later milestone) append messages to
``inbox/pending.jsonl``. At the start of each wake step the agent process
atomically drains the pending queue into ``inbox/delivered.jsonl`` and hands the
freshly delivered messages to the recall context as "things an observer left"
(neutral framing — the agent is free to ignore them, spec §3).

Concurrency (spec P5): the web process only ever *appends* to pending; the agent
is the only process that moves pending -> delivered. A small ``inbox.lock`` file
guards the move so an append that races the drain cannot lose a line. The lock
is a best-effort advisory file created with ``O_CREAT | O_EXCL``.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..paths import DataPaths


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _next_inbox_id(existing: list[dict[str, Any]]) -> int:
    """Highest numeric suffix of any ``in-XXXX`` id seen so far, plus one."""
    highest = 0
    for m in existing:
        mid = str(m.get("id") or "")
        if mid.startswith("in-"):
            try:
                highest = max(highest, int(mid[3:]))
            except ValueError:
                continue
    return highest + 1


class _InboxLock:
    """A tiny advisory lock (O_EXCL create). Blocks briefly, then steals stale."""

    def __init__(self, path: Path, *, timeout: float = 5.0, stale: float = 30.0) -> None:
        self.path = path
        self.timeout = timeout
        self.stale = stale
        self._fd: int | None = None

    def __enter__(self) -> "_InboxLock":
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


def append_pending(paths: DataPaths, text: str, *, kind: str = "message",
                   meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Append one observer message to the pending queue (used by the web layer).

    Returns the stored record (with its assigned ``id`` and timestamp).
    """
    paths.inbox_dir.mkdir(parents=True, exist_ok=True)
    with _InboxLock(paths.inbox_lock):
        existing = _read_jsonl(paths.inbox_pending) + _read_jsonl(paths.inbox_delivered)
        record = {
            "id": f"in-{_next_inbox_id(existing):04d}",
            "ts": _now_iso(),
            "kind": kind,
            "text": text,
            "meta": meta or {},
        }
        with paths.inbox_pending.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def has_pending(paths: DataPaths) -> bool:
    """True if there is at least one undelivered observer message."""
    return bool(_read_jsonl(paths.inbox_pending))


def peek_pending(paths: DataPaths) -> list[dict[str, Any]]:
    """Return the currently pending messages without draining them."""
    return _read_jsonl(paths.inbox_pending)


def drain(paths: DataPaths) -> list[dict[str, Any]]:
    """Atomically move all pending messages into delivered; return them.

    Called at the start of each wake step (spec P5). The move is guarded by the
    inbox lock so a concurrent ``append_pending`` cannot lose a line. Each
    delivered record gets a ``delivered_ts`` stamp.
    """
    paths.inbox_dir.mkdir(parents=True, exist_ok=True)
    with _InboxLock(paths.inbox_lock):
        pending = _read_jsonl(paths.inbox_pending)
        if not pending:
            return []

        now = _now_iso()
        for m in pending:
            m["delivered_ts"] = now

        # Append to delivered first, then truncate pending. If we crash between
        # the two, the worst case is a message delivered twice — never lost.
        with paths.inbox_delivered.open("a", encoding="utf-8") as fh:
            for m in pending:
                fh.write(json.dumps(m, ensure_ascii=False) + "\n")
        # Truncate the pending file (atomic replace with empty).
        tmp = paths.inbox_pending.with_name(
            f"{paths.inbox_pending.name}.tmp-{os.getpid()}"
        )
        tmp.write_text("", encoding="utf-8")
        os.replace(tmp, paths.inbox_pending)

    return pending


def read_delivered(paths: DataPaths) -> list[dict[str, Any]]:
    """Return the full delivered history (chronological)."""
    return _read_jsonl(paths.inbox_delivered)
