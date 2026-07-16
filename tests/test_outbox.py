"""Outbox tests: observer-request channel (append-only files, derived status)."""

from __future__ import annotations

import pytest

from soul.storage import outbox


def test_append_request_id_increments(data_paths):
    a = outbox.append_request(data_paths, "install numpy")
    b = outbox.append_request(data_paths, "fetch this paper", step_id="step-000042")
    assert a["id"] == "req-0001"
    assert b["id"] == "req-0002"
    assert b["step_id"] == "step-000042"
    assert a["step_id"] is None

    # Records landed on disk and survive a fresh read.
    reqs = outbox.list_requests(data_paths)
    assert [r["id"] for r in reqs] == ["req-0001", "req-0002"]
    assert [r["text"] for r in reqs] == ["install numpy", "fetch this paper"]


def test_derived_status_open_then_resolved(data_paths):
    outbox.append_request(data_paths, "please help")
    [req] = outbox.list_requests(data_paths)
    assert req["status"] == "open"
    assert req["resolved_ts"] is None
    assert req["observer_note"] is None
    assert req["attachment"] is None

    res = outbox.append_resolution(
        data_paths, "req-0001", "resolved",
        note="installed it", attachment="req-0001/paper.pdf",
    )
    [req] = outbox.list_requests(data_paths)
    assert req["status"] == "resolved"
    assert req["observer_note"] == "installed it"
    assert req["attachment"] == "req-0001/paper.pdf"
    assert req["resolved_ts"] == res["ts"]


def test_last_record_wins(data_paths):
    # ignore then reopen -> derives back to open.
    outbox.append_request(data_paths, "first")
    outbox.append_resolution(data_paths, "req-0001", "ignored")
    assert outbox.list_requests(data_paths)[0]["status"] == "ignored"
    outbox.append_resolution(data_paths, "req-0001", "reopened")
    assert outbox.list_requests(data_paths)[0]["status"] == "open"
    assert outbox.open_requests(data_paths)[0]["id"] == "req-0001"

    # ignore then resolve -> resolved.
    outbox.append_request(data_paths, "second")
    outbox.append_resolution(data_paths, "req-0002", "ignored")
    outbox.append_resolution(data_paths, "req-0002", "resolved", note="done")
    got = {r["id"]: r["status"] for r in outbox.list_requests(data_paths)}
    assert got["req-0002"] == "resolved"


def test_list_requests_status_filter(data_paths):
    outbox.append_request(data_paths, "a")
    outbox.append_request(data_paths, "b")
    outbox.append_resolution(data_paths, "req-0002", "resolved")
    assert [r["id"] for r in outbox.list_requests(data_paths, status="open")] == ["req-0001"]
    assert [r["id"] for r in outbox.list_requests(data_paths, status="resolved")] == ["req-0002"]
    with pytest.raises(ValueError):
        outbox.list_requests(data_paths, status="bogus")


def test_append_resolution_errors(data_paths):
    outbox.append_request(data_paths, "x")

    with pytest.raises(KeyError):
        outbox.append_resolution(data_paths, "req-9999", "resolved")

    with pytest.raises(ValueError):
        outbox.append_resolution(data_paths, "req-0001", "not-a-status")

    # reopen on an open (non-ignored) request is invalid.
    with pytest.raises(outbox.OutboxStateError):
        outbox.append_resolution(data_paths, "req-0001", "reopened")

    # resolve then resolve again -> terminal, invalid.
    outbox.append_resolution(data_paths, "req-0001", "resolved")
    with pytest.raises(outbox.OutboxStateError):
        outbox.append_resolution(data_paths, "req-0001", "resolved")


def test_drain_surfaces_resolved_once(data_paths, tmp_path):
    home = tmp_path / "home"
    outbox.append_request(data_paths, "help me")
    outbox.append_resolution(data_paths, "req-0001", "resolved", note="here you go")

    drained = outbox.drain_new_resolutions(data_paths, home_dir=home)
    assert len(drained) == 1
    assert drained[0]["id"] == "req-0001"
    assert drained[0]["text"] == "help me"
    assert drained[0]["status"] == "resolved"
    assert drained[0]["note"] == "here you go"

    # Idempotent: a second drain surfaces nothing.
    assert outbox.drain_new_resolutions(data_paths, home_dir=home) == []


def test_drain_skips_ignored_but_later_resolve_surfaces(data_paths, tmp_path):
    home = tmp_path / "home"
    outbox.append_request(data_paths, "need a dataset")

    outbox.append_resolution(data_paths, "req-0001", "ignored")
    # ignored is never surfaced, but the cursor advances past it.
    assert outbox.drain_new_resolutions(data_paths, home_dir=home) == []

    outbox.append_resolution(data_paths, "req-0001", "resolved", note="attached")
    drained = outbox.drain_new_resolutions(data_paths, home_dir=home)
    assert [d["id"] for d in drained] == ["req-0001"]
    assert drained[0]["status"] == "resolved"


def test_drain_surfaces_declined_with_note(data_paths, tmp_path):
    home = tmp_path / "home"
    outbox.append_request(data_paths, "buy me a gpu")
    outbox.append_resolution(data_paths, "req-0001", "declined", note="no budget")
    drained = outbox.drain_new_resolutions(data_paths, home_dir=home)
    assert len(drained) == 1
    assert drained[0]["status"] == "declined"
    assert drained[0]["note"] == "no budget"


def test_drain_copies_attachment_into_home(data_paths):
    home = data_paths.root / "home"
    outbox.append_request(data_paths, "send the pdf")

    src = data_paths.outbox_attachments_dir / "req-0001"
    src.mkdir(parents=True, exist_ok=True)
    (src / "x.txt").write_text("hello", encoding="utf-8")

    outbox.append_resolution(
        data_paths, "req-0001", "resolved", attachment="req-0001/x.txt",
    )
    drained = outbox.drain_new_resolutions(data_paths, home_dir=home)
    assert drained[0]["attachment"] == "req-0001/x.txt"

    copied = home / "attachments" / "req-0001" / "x.txt"
    assert copied.is_file()
    assert copied.read_text(encoding="utf-8") == "hello"


def test_drain_tolerates_missing_attachment(data_paths, tmp_path):
    home = tmp_path / "home"
    outbox.append_request(data_paths, "send the pdf")
    outbox.append_resolution(
        data_paths, "req-0001", "resolved", attachment="req-0001/missing.txt",
    )
    # Missing source file: record still surfaces, no copy made.
    drained = outbox.drain_new_resolutions(data_paths, home_dir=home)
    assert len(drained) == 1
    assert not (home / "attachments" / "req-0001" / "missing.txt").exists()


def test_lock_file_cleaned_up(data_paths):
    outbox.append_request(data_paths, "x")
    outbox.append_resolution(data_paths, "req-0001", "resolved")
    assert not data_paths.outbox_lock.exists()
