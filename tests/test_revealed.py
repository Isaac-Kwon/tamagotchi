"""revealed_interest tests (M2): pure derivation from journal fixtures (P2)."""

from __future__ import annotations

from soul.storage import journal


def _step(thread_id, topic, decision, interest):
    return {
        "kind": "wake_step",
        "thread_id": thread_id,
        "topic": topic,
        "decision": decision,
        "interest": interest,
    }


def _fixture_steps():
    # A long thread on "A", shelved, an unrelated "B", then a return to "A".
    return [
        _step("th-1", "A", "deepen", 7),
        _step("th-1", "A", "deepen", 8),
        _step("th-1", "A", "shelve", 6),
        _step("th-2", "B", "new", 3),
        _step("th-3", "A", "deepen", 9),
        _step("th-3", "A", "deepen", 9),
    ]


def test_thread_durations_and_top_threads():
    rev = journal.revealed_interest(_fixture_steps())
    top = rev["top_threads"]
    assert top[0]["thread_id"] == "th-1"
    assert top[0]["steps"] == 3
    assert top[1]["thread_id"] == "th-3"
    assert top[1]["steps"] == 2


def test_shelve_then_return_counted():
    rev = journal.revealed_interest(_fixture_steps())
    assert rev["shelve_returns"] == {"A": 1}
    assert rev["total_shelve_returns"] == 1


def test_topic_recurrence():
    rev = journal.revealed_interest(_fixture_steps())
    # "A" recurs across 5 steps; "B" appears once so is not "recurrent".
    assert rev["topic_recurrence"] == {"A": 5}


def test_stated_average_and_note():
    rev = journal.revealed_interest(_fixture_steps())
    assert rev["stated_avg_interest"] == 7.0
    note = rev["stated_vs_revealed_note"]
    assert "Longest thread ran 3" in note
    assert "Returned to after shelving" in note


def test_empty_journal_is_safe():
    rev = journal.revealed_interest([])
    assert rev["top_threads"] == []
    assert rev["stated_vs_revealed_note"] is None


def test_non_wake_steps_ignored():
    steps = [{"kind": "error", "thread_id": "th-9", "topic": "X"}]
    rev = journal.revealed_interest(steps)
    assert rev["threads"] == []
