"""Tests for storage: state atomic write and journal append/tail (M1)."""

from __future__ import annotations

import json

from soul.storage import journal, state as state_store


def test_state_atomic_write_and_read(data_paths):
    st = state_store.default_state()
    st["status"] = "awake"
    state_store.write_state(data_paths.state_json, st)
    back = state_store.read_state(data_paths.state_json)
    assert back["status"] == "awake"
    assert "updated_at" in back
    # No leftover temp files in the directory.
    tmps = list(data_paths.root.glob("state.json.tmp-*"))
    assert not tmps


def test_state_read_fallback_on_corruption(data_paths):
    data_paths.state_json.write_text("{ not json", encoding="utf-8")
    st = state_store.read_state(data_paths.state_json)
    assert st["status"] == "idle"  # default snapshot


def test_state_read_fallback_on_missing(tmp_path):
    st = state_store.read_state(tmp_path / "does-not-exist.json")
    assert st["step_counter"] == 0


def test_next_step_id_increments(data_paths):
    sid1, st1 = state_store.next_step_id(data_paths.state_json)
    state_store.write_state(data_paths.state_json, st1)
    sid2, st2 = state_store.next_step_id(data_paths.state_json)
    assert sid1 == "step-000001"
    assert sid2 == "step-000002"


def test_journal_append_and_tail(data_paths):
    for i in range(3):
        rec = journal.new_step_record(f"step-{i:06d}", summary=f"s{i}")
        journal.append_step(data_paths, rec)
    last2 = journal.tail(data_paths, 2)
    assert [r["summary"] for r in last2] == ["s1", "s2"]


def test_journal_record_has_full_schema(data_paths):
    rec = journal.new_step_record("step-000001")
    for field in ("id", "ts", "kind", "action", "topic", "thread_id",
                  "content_path", "interest", "interest_delta", "mood",
                  "reason", "decision", "summary", "soul_updated", "soul_commit",
                  "serendipity_note", "transcript_path", "wiki_ops", "web_visits",
                  "skill_used", "sandbox_backend", "preempted", "inbox_delivered",
                  "llm", "error"):
        assert field in rec, f"missing schema field {field}"


def test_journal_line_is_valid_json(data_paths):
    journal.append_step(data_paths, journal.new_step_record("step-000001"))
    path = data_paths.journal_file()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    json.loads(lines[0])  # parses
