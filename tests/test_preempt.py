"""Loop-side chat preemption + crash recovery (M6 boundary behaviour, spec P7)."""

from __future__ import annotations

from soul.agent import loop, preempt
from soul.agent.fake_llm import FakeLLM
from soul.agent.preempt import StepController
from soul.storage import control, journal, state as state_store


def _act(topic="t", content="# n\n\nbody"):
    return {"action": "free_write", "topic": topic, "content": content}


def _reflect(**over):
    base = {
        "interest": 6, "interest_delta": "first", "mood": "curious",
        "reason": "r", "decision": "new", "summary": "s",
        "soul_update": {"update": False, "content": "", "reason": ""},
    }
    base.update(over)
    return base


def test_step_pauses_snapshots_and_resumes(config, data_paths):
    """Chat active at a boundary -> snapshot + status=chatting -> resume on end."""
    config.chat.preempt_poll_seconds = 1

    # A chat is live when the step begins.
    control.set_chat_active(data_paths, "sess-1")

    observed = {}

    def fake_sleep(_seconds):
        # We are now polling, which means: snapshot written + status=chatting.
        snap = control.read_paused_step(data_paths)
        observed["snapshot"] = snap
        st = state_store.read_state(data_paths.state_json)
        observed["status"] = st["status"]
        # The user ends the chat -> next poll sees it inactive -> loop resumes.
        control.set_chat_inactive(data_paths)

    controller = StepController(data_paths, config, sleep=fake_sleep)
    llm = FakeLLM([_act(), _reflect()])
    record = loop.run_step(config, data_paths, llm, controller=controller)

    # Paused at the first (ACT) boundary: snapshot captured the phase.
    assert observed["snapshot"] is not None
    assert observed["snapshot"]["phase"] == "act"
    assert observed["snapshot"]["step_id"] == "step-000001"
    assert observed["status"] == "chatting"

    # Resumed and completed the step; marked preempted.
    assert record["kind"] == "wake_step"
    assert record["preempted"] is True

    # Snapshot cleared after resume; step artifacts exist.
    assert control.read_paused_step(data_paths) is None
    assert (data_paths.notes_dir / "step-000001.md").exists()


def test_no_preempt_when_chat_inactive(config, data_paths):
    control.set_chat_inactive(data_paths)
    called = {"n": 0}

    def fake_sleep(_s):
        called["n"] += 1

    controller = StepController(data_paths, config, sleep=fake_sleep)
    llm = FakeLLM([_act(), _reflect()])
    record = loop.run_step(config, data_paths, llm, controller=controller)
    assert record["preempted"] is False
    assert called["n"] == 0  # never polled


def test_max_wait_resumes_even_if_chat_stays_active(config, data_paths):
    """preempt_max_wait exceeded -> resume even while chat is still active."""
    config.chat.preempt_poll_seconds = 1
    config.chat.preempt_max_wait_minutes = 0  # immediate ceiling

    control.set_chat_active(data_paths, "sess-2")

    controller = StepController(data_paths, config, sleep=lambda s: None)
    llm = FakeLLM([_act(), _reflect()])
    record = loop.run_step(config, data_paths, llm, controller=controller)
    # Chat was never ended, but the max-wait ceiling let the step resume.
    assert record["kind"] == "wake_step"
    assert record["preempted"] is True


def test_recover_paused_step_records_error(config, data_paths):
    """A leftover snapshot on restart -> error step (preempted) + cleared."""
    control.write_paused_step(data_paths, {"step_id": "step-000042", "phase": "tools"})
    control.set_chat_active(data_paths, "sess-3")

    snap = preempt.recover_paused_step(data_paths)
    assert snap is not None

    errs = [s for s in journal.read_all(data_paths)
            if s.get("kind") == "error" and s.get("id") == "step-000042"]
    assert len(errs) == 1
    assert errs[0]["preempted"] is True

    # Snapshot cleared and chat reset.
    assert control.read_paused_step(data_paths) is None
    assert control.read_chat(data_paths)["active"] is False


def test_recover_paused_step_none_when_no_snapshot(config, data_paths):
    assert preempt.recover_paused_step(data_paths) is None
