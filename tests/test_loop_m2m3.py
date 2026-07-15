"""Integration tests (M2/M3): thread persistence, sandbox, inbox delivery."""

from __future__ import annotations

from soul.agent import loop
from soul.agent.fake_llm import FakeLLM
from soul.storage import inbox, journal, state as state_store


def _act(action="free_write", topic="t", content="# n\n\nbody"):
    return {"action": action, "topic": topic, "content": content}


def _reflect(**over):
    base = {
        "interest": 7, "interest_delta": "same", "mood": "curious",
        "reason": "r", "decision": "deepen", "summary": "s",
        "soul_update": {"update": False, "content": "", "reason": ""},
    }
    base.update(over)
    return base


def test_deepen_keeps_thread_over_three_steps(config, data_paths):
    ids = []
    for _ in range(3):
        llm = FakeLLM([_act(topic="T"), _reflect(decision="deepen")])
        ids.append(loop.run_step(config, data_paths, llm)["thread_id"])
    assert ids[0] == ids[1] == ids[2]

    # The state reflects a growing thread with an interest series.
    st = state_store.read_state(data_paths.state_json)
    assert st["current_thread"]["steps"] == 3
    assert len(st["current_thread"]["interest_series"]) == 3


def test_shelve_records_in_state_and_abandon_resets(config, data_paths):
    llm1 = FakeLLM([_act(topic="Shelved"), _reflect(decision="shelve")])
    loop.run_step(config, data_paths, llm1)
    st = state_store.read_state(data_paths.state_json)
    assert st["current_thread"] is None
    assert any(t["topic"] == "Shelved" for t in st["shelved_threads"])

    llm2 = FakeLLM([_act(topic="Fresh"), _reflect(decision="abandon")])
    r2 = loop.run_step(config, data_paths, llm2)
    st2 = state_store.read_state(data_paths.state_json)
    assert st2["current_thread"] is None
    assert r2["decision"] == "abandon"


def test_code_experiment_runs_through_sandbox(config, data_paths):
    config.sandbox.backend = "subprocess"
    code_content = "Trying arithmetic.\n\n```python\nprint(6 * 7)\n```\n"
    llm = FakeLLM([
        _act(action="code_experiment", topic="math", content=code_content),
        _reflect(decision="new"),
    ])
    record = loop.run_step(config, data_paths, llm)

    assert record["action"] == "code_experiment"
    assert record["sandbox_backend"] == "subprocess"
    note = (data_paths.notes_dir / f"{record['id']}.md").read_text(encoding="utf-8")
    assert "42" in note          # the executed output was appended
    assert "Execution" in note


def test_inbox_delivered_into_step(config, data_paths):
    inbox.append_pending(data_paths, "a note from an observer")
    llm = FakeLLM([_act(), _reflect(decision="new")])
    record = loop.run_step(config, data_paths, llm)

    assert record["inbox_delivered"] == ["in-0001"]
    # It was moved out of pending during the step.
    assert inbox.has_pending(data_paths) is False
    assert len(inbox.read_delivered(data_paths)) == 1


def test_revealed_snapshot_written_to_state(config, data_paths):
    for _ in range(2):
        llm = FakeLLM([_act(topic="Recurring"), _reflect(decision="deepen")])
        loop.run_step(config, data_paths, llm)
    st = state_store.read_state(data_paths.state_json)
    assert st["revealed"]["stated_vs_revealed_note"]
    assert st["revealed"]["top_threads"]
