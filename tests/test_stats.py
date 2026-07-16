"""Tests for journal.stats — the pure aggregation behind the UI stats panel."""

from __future__ import annotations

from soul.storage import journal


def _wake(i, *, action="free_write", topic="T", thread="th-0001",
          interest=7, mood="curious", decision="deepen"):
    return journal.new_step_record(
        f"step-{i:06d}", ts=f"2026-07-15T0{i % 10}:00:00+00:00",
        action=action, topic=topic, thread_id=thread,
        interest=interest, mood=mood, decision=decision,
    )


def _error(i, *, phase="act", message="boom"):
    return journal.new_step_record(
        f"step-{i:06d}", kind="error",
        error={"phase": phase, "message": message, "llm_failure": False},
    )


def test_stats_empty():
    s = journal.stats([])
    assert s["total_steps"] == 0
    assert s["decisions"] == {}
    assert s["threads"] == []
    assert s["errors"] == {"count": 0, "recent": []}


def test_stats_distributions():
    steps = [
        _wake(1, decision="deepen", mood="curious", interest=8, action="free_write"),
        _wake(2, decision="deepen", mood="proud", interest=8, action="code_experiment"),
        _wake(3, decision="new", mood="curious", interest=6, action="free_write"),
    ]
    s = journal.stats(steps)
    assert s["total_steps"] == 3
    assert s["decisions"] == {"deepen": 2, "new": 1}
    assert s["actions"] == {"free_write": 2, "code_experiment": 1}
    assert s["moods"] == {"curious": 2, "proud": 1}
    assert s["interest_hist"] == {"6": 1, "8": 2}


def test_stats_thread_segments_group_consecutive_ids():
    steps = [
        _wake(1, thread="th-0001", topic="first wording", interest=6),
        _wake(2, thread="th-0001", topic="second wording", interest=8),
        _wake(3, thread="th-0003", topic="other", interest=7, decision="new"),
    ]
    s = journal.stats(steps)
    assert [t["thread_id"] for t in s["threads"]] == ["th-0001", "th-0003"]
    seg = s["threads"][0]
    assert seg["steps"] == 2
    assert seg["topic"] == "second wording"  # label follows the latest wording
    assert seg["avg_interest"] == 7.0
    assert seg["start_ts"] < seg["end_ts"]


def test_stats_errors_collected_and_capped():
    steps = [_error(i) for i in range(1, 6)]
    s = journal.stats(steps, recent_errors=3)
    assert s["errors"]["count"] == 5
    assert len(s["errors"]["recent"]) == 3
    assert s["errors"]["recent"][-1]["id"] == "step-000005"
    assert s["errors"]["recent"][0]["phase"] == "act"
    # error records are not wake steps
    assert s["total_steps"] == 0


def test_stats_timeline_limit():
    steps = [_wake(i) for i in range(1, 11)]
    s = journal.stats(steps, timeline_limit=4)
    assert len(s["timeline"]) == 4
    assert s["timeline"][-1]["id"] == "step-000010"
    # distributions still cover ALL steps, not just the timeline window
    assert s["total_steps"] == 10


def test_stats_skips_non_wake_records():
    steps = [_wake(1), {"kind": "report", "id": "r1"}]
    s = journal.stats(steps)
    assert s["total_steps"] == 1
