"""Inbox tests (M2): pending -> delivered atomic move (spec P4/P5)."""

from __future__ import annotations

from soul.storage import inbox


def test_append_and_has_pending(data_paths):
    assert inbox.has_pending(data_paths) is False
    rec = inbox.append_pending(data_paths, "have you tried tea?")
    assert rec["id"] == "in-0001"
    assert rec["text"] == "have you tried tea?"
    assert inbox.has_pending(data_paths) is True


def test_ids_increment_across_pending_and_delivered(data_paths):
    inbox.append_pending(data_paths, "one")
    inbox.append_pending(data_paths, "two")
    inbox.drain(data_paths)
    third = inbox.append_pending(data_paths, "three")
    # id keeps climbing even though the first two are now delivered.
    assert third["id"] == "in-0003"


def test_drain_moves_pending_to_delivered(data_paths):
    inbox.append_pending(data_paths, "first")
    inbox.append_pending(data_paths, "second")

    delivered = inbox.drain(data_paths)
    assert [m["text"] for m in delivered] == ["first", "second"]
    assert all("delivered_ts" in m for m in delivered)

    # Pending is now empty; delivered has both.
    assert inbox.has_pending(data_paths) is False
    assert inbox.peek_pending(data_paths) == []
    assert len(inbox.read_delivered(data_paths)) == 2

    # A second drain yields nothing (idempotent, no double delivery).
    assert inbox.drain(data_paths) == []


def test_lock_file_cleaned_up(data_paths):
    inbox.append_pending(data_paths, "x")
    inbox.drain(data_paths)
    assert not data_paths.inbox_lock.exists()
