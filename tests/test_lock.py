"""Tests for agent.lock: acquisition, stale takeover, live rejection (M1)."""

from __future__ import annotations

import json
import os

import pytest

from soul.agent.lock import AgentLock, LockError


def test_acquire_and_release(tmp_path):
    lock_path = tmp_path / "agent.lock"
    with AgentLock(lock_path):
        assert lock_path.exists()
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        assert data["pid"] == os.getpid()
    assert not lock_path.exists()


def test_stale_lock_takeover(tmp_path):
    """A lock owned by a dead pid must be taken over."""
    lock_path = tmp_path / "agent.lock"
    # A pid that is essentially guaranteed not to be running.
    dead_pid = 2_000_000_000
    lock_path.write_text(
        json.dumps({"pid": dead_pid, "acquired_at": "2000-01-01T00:00:00+0000"}),
        encoding="utf-8",
    )
    with AgentLock(lock_path):
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        assert data["pid"] == os.getpid()  # taken over


def test_live_lock_rejected(tmp_path):
    """A lock owned by a live pid (this process) must be rejected."""
    lock_path = tmp_path / "agent.lock"
    lock_path.write_text(
        json.dumps({"pid": _other_live_pid(), "acquired_at": "x"}),
        encoding="utf-8",
    )
    with pytest.raises(LockError):
        AgentLock(lock_path).acquire()


def _other_live_pid() -> int:
    """A pid that is alive but not ours — use the parent process (or ours)."""
    ppid = os.getppid()
    return ppid if ppid > 0 else os.getpid()


def test_corrupt_lock_is_taken_over(tmp_path):
    lock_path = tmp_path / "agent.lock"
    lock_path.write_text("not json at all", encoding="utf-8")
    with AgentLock(lock_path):
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        assert data["pid"] == os.getpid()
