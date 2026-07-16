"""Tests for storage: state atomic write and journal append/tail (M1)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

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
    path = journal.append_step(data_paths, journal.new_step_record("step-000001"))
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    json.loads(lines[0])  # parses


def test_journal_first_chunk_naming(data_paths):
    """First append of the hour lands in an hourly -00 chunk (steps-YYYY-MM-DD-HH-NN)."""
    path = journal.append_step(data_paths, journal.new_step_record("step-000001"))
    hour = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H")
    assert path.name == f"steps-{hour}-00.jsonl"


def test_journal_rolls_to_next_chunk_after_50(data_paths):
    """50 records fill -00; the 51st opens -01 (within the same hour)."""
    hour = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H")
    paths_seen = []
    for i in range(51):
        p = journal.append_step(data_paths, journal.new_step_record(f"step-{i:06d}"))
        paths_seen.append(p)
    chunk00 = data_paths.journal_dir / f"steps-{hour}-00.jsonl"
    chunk01 = data_paths.journal_dir / f"steps-{hour}-01.jsonl"
    assert chunk00.read_text(encoding="utf-8").splitlines().__len__() == 50
    assert chunk01.read_text(encoding="utf-8").splitlines().__len__() == 1
    assert paths_seen[49].name == f"steps-{hour}-00.jsonl"
    assert paths_seen[50].name == f"steps-{hour}-01.jsonl"
    # All 51 read back in order.
    assert [r["id"] for r in journal.read_all(data_paths)] == [
        f"step-{i:06d}" for i in range(51)
    ]


def test_journal_records_span_hours_into_per_hour_files(data_paths):
    """Records from different UTC hours land in per-hour chunk files."""
    h1 = datetime(2026, 7, 16, 8, 30, tzinfo=timezone.utc)
    h2 = datetime(2026, 7, 16, 9, 5, tzinfo=timezone.utc)
    (data_paths.journal_dir / f"{data_paths.journal_hour_prefix(h1)}-00.jsonl").write_text(
        json.dumps(journal.new_step_record("step-000001")) + "\n", encoding="utf-8"
    )
    (data_paths.journal_dir / f"{data_paths.journal_hour_prefix(h2)}-00.jsonl").write_text(
        json.dumps(journal.new_step_record("step-000002")) + "\n", encoding="utf-8"
    )
    names = sorted(p.name for p in data_paths.journal_dir.glob("steps-*.jsonl"))
    assert names == ["steps-2026-07-16-08-00.jsonl", "steps-2026-07-16-09-00.jsonl"]
    assert [r["id"] for r in journal.read_all(data_paths)] == ["step-000001", "step-000002"]


def test_journal_reads_mixed_monthly_and_hourly_in_order(data_paths):
    """Legacy monthly files read *before* the hourly chunks migrated from them.

    A naive lexicographic sort gets this wrong ('-' 0x2D < '.' 0x2E puts the
    hourly chunk first); _journal_sort_key must keep the monthly backlog ahead.
    """
    jd = data_paths.journal_dir
    # Legacy monthly file (older backlog) — two records.
    (jd / "steps-2026-07.jsonl").write_text(
        json.dumps(journal.new_step_record("step-000001")) + "\n"
        + json.dumps(journal.new_step_record("step-000002")) + "\n",
        encoding="utf-8",
    )
    # New hourly chunks for the same month, migrated later.
    (jd / "steps-2026-07-16-09-00.jsonl").write_text(
        json.dumps(journal.new_step_record("step-000003")) + "\n", encoding="utf-8"
    )
    (jd / "steps-2026-07-16-09-01.jsonl").write_text(
        json.dumps(journal.new_step_record("step-000004")) + "\n", encoding="utf-8"
    )
    # A later hour's chunk.
    (jd / "steps-2026-07-16-10-00.jsonl").write_text(
        json.dumps(journal.new_step_record("step-000005")) + "\n", encoding="utf-8"
    )
    ids = [r["id"] for r in journal.read_all(data_paths)]
    assert ids == ["step-000001", "step-000002", "step-000003", "step-000004", "step-000005"]
    # tail crosses file boundaries too.
    assert [r["id"] for r in journal.tail(data_paths, 3)] == [
        "step-000003", "step-000004", "step-000005",
    ]
