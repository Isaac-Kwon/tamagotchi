"""Tests for the wake-step orchestration (M1).

Uses the FakeLLM scenario queue (spec P10). Each wake step consumes two chat
calls: ACT then REFLECT (plus a correction re-call under the JSON fallback).
"""

from __future__ import annotations

import json
import subprocess

from soul.agent import loop
from soul.agent.fake_llm import FakeLLM
from soul.storage import journal, state as state_store


def _act(action="free_write", topic="a topic", content="# Note\n\nbody"):
    return {"action": action, "topic": topic, "content": content}


def _reflect(**over):
    base = {
        "interest": 6,
        "interest_delta": "first",
        "mood": "curious",
        "reason": "it felt engaging",
        "decision": "deepen",
        "summary": "wrote a short note",
        "soul_update": {"update": False, "content": "", "reason": ""},
    }
    base.update(over)
    return base


def test_one_full_mock_step_produces_artifacts(config, data_paths):
    llm = FakeLLM([_act(), _reflect()])
    record = loop.run_step(config, data_paths, llm)

    # 1 journal line.
    steps = journal.read_all(data_paths)
    assert len(steps) == 1
    assert steps[0]["id"] == "step-000001"
    assert steps[0]["kind"] == "wake_step"

    # notes file.
    note = data_paths.notes_dir / "step-000001.md"
    assert note.exists()
    assert "body" in note.read_text(encoding="utf-8")
    assert record["content_path"] == "notes/step-000001.md"

    # transcript file with 2 round-trips (ACT + REFLECT).
    transcript = data_paths.transcript_file("step-000001")
    assert transcript.exists()
    tlines = transcript.read_text(encoding="utf-8").splitlines()
    assert len(tlines) == 2

    # state.json updated.
    st = state_store.read_state(data_paths.state_json)
    assert st["step_counter"] == 1
    assert st["last_step"]["id"] == "step-000001"
    assert st["status"] == "awake"


def test_soul_update_triggers_commit_recorded_in_journal(config, data_paths):
    new_soul = "# SOUL\n\nI am becoming someone who writes."
    llm = FakeLLM([
        _act(),
        _reflect(soul_update={"update": True, "content": new_soul, "reason": "durable"}),
    ])
    record = loop.run_step(config, data_paths, llm)

    assert record["soul_updated"] is True
    commit = record["soul_commit"]
    assert commit

    # The commit hash is real in the data repo.
    result = subprocess.run(
        ["git", "-C", str(data_paths.root), "cat-file", "-t", commit],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "commit"

    # SOUL.md content actually changed.
    assert "writes" in data_paths.soul_md.read_text(encoding="utf-8")


def test_json_fallback_stage2_prose_wrapped(config, data_paths):
    """ACT returns JSON wrapped in prose -> outermost-braces extraction works."""
    prose = "Sure, here you go:\n```json\n" + json.dumps(_act()) + "\n```\nDone."
    llm = FakeLLM([prose, _reflect()])
    record = loop.run_step(config, data_paths, llm)
    assert record["kind"] == "wake_step"
    assert record["action"] == "free_write"


def test_json_fallback_stage3_correction_recall(config, data_paths):
    """ACT broken once, then correction re-call returns clean JSON."""
    llm = FakeLLM(["totally not json", _act(), _reflect()])
    record = loop.run_step(config, data_paths, llm)
    assert record["kind"] == "wake_step"
    # ACT consumed 2 calls (broken + correction), REFLECT 1 = 3 total.
    assert len(llm.calls) == 3


def test_json_fallback_broken_twice_records_error(config, data_paths):
    """ACT broken twice (original + correction) -> kind:error step, skip."""
    llm = FakeLLM(["not json", "still not json"])
    record = loop.run_step(config, data_paths, llm)
    assert record["kind"] == "error"
    assert record["error"]["phase"] == "act"

    st = state_store.read_state(data_paths.state_json)
    assert st["status"] == "error"
    # No notes file for a failed ACT.
    assert not (data_paths.notes_dir / "step-000001.md").exists()


def test_interest_clamped(config, data_paths):
    llm = FakeLLM([_act(), _reflect(interest=99)])
    record = loop.run_step(config, data_paths, llm)
    assert record["interest"] == 10

    llm2 = FakeLLM([_act(), _reflect(interest=-5)])
    record2 = loop.run_step(config, data_paths, llm2)
    assert record2["interest"] == 1


def test_mood_normalized_with_raw_preserved(config, data_paths):
    llm = FakeLLM([_act(), _reflect(mood="ecstatic-nonsense")])
    record = loop.run_step(config, data_paths, llm)
    assert record["mood"] == "neutral"
    assert record["mood_raw"] == "ecstatic-nonsense"


def test_decision_out_of_enum_defaults(config, data_paths):
    llm = FakeLLM([_act(), _reflect(decision="ponder")])
    record = loop.run_step(config, data_paths, llm)
    assert record["decision"] == "new"


def test_deepen_keeps_thread_id(config, data_paths):
    # Step 1: deepen on topic T.
    llm1 = FakeLLM([_act(topic="T"), _reflect(decision="deepen")])
    r1 = loop.run_step(config, data_paths, llm1)
    # Step 2: same topic T, deepen again -> same thread_id.
    llm2 = FakeLLM([_act(topic="T"), _reflect(decision="deepen")])
    r2 = loop.run_step(config, data_paths, llm2)
    assert r1["thread_id"] == r2["thread_id"]


def test_new_decision_starts_fresh_thread(config, data_paths):
    llm1 = FakeLLM([_act(topic="T"), _reflect(decision="new")])
    r1 = loop.run_step(config, data_paths, llm1)
    llm2 = FakeLLM([_act(topic="U"), _reflect(decision="deepen")])
    r2 = loop.run_step(config, data_paths, llm2)
    assert r1["thread_id"] != r2["thread_id"]
