"""Tests for the scheduler: long-step policy, circuit breaker, next_wake_at (M5)."""

from __future__ import annotations

from datetime import datetime, timezone

from soul.agent import scheduler
from soul.agent.fake_llm import FakeLLM
from soul.agent.llm import LLMError
from soul.agent.preempt import StepController
from soul.storage import state as state_store


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


class _ScriptedClock:
    """Returns a scripted sequence of monotonic values (start/end per step)."""

    def __init__(self, values):
        self._values = list(values)
        self._i = 0

    def __call__(self):
        v = self._values[min(self._i, len(self._values) - 1)]
        self._i += 1
        return v


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def test_compute_wait_heartbeat_short_step(config):
    config.agent.mode = "heartbeat"
    config.agent.heartbeat_minutes = 10
    config.agent.min_step_gap_seconds = 60
    # step 0..60s (1 min). Next start = max(0+600, 60+60)=600 -> wait 540.
    assert scheduler.compute_wait(config, 0.0, 60.0) == 540.0


def test_compute_wait_heartbeat_long_step_uses_min_gap(config):
    config.agent.mode = "heartbeat"
    config.agent.heartbeat_minutes = 10   # 600s
    config.agent.min_step_gap_seconds = 60
    # step 0..800s (longer than heartbeat). max(0+600, 800+60)=860 -> wait 60.
    assert scheduler.compute_wait(config, 0.0, 800.0) == 60.0


def test_compute_wait_continuous(config):
    config.agent.mode = "continuous"
    config.agent.min_step_gap_seconds = 45
    assert scheduler.compute_wait(config, 0.0, 500.0) == 45.0


def test_compute_wait_circuit_factor(config):
    config.agent.mode = "heartbeat"
    config.agent.heartbeat_minutes = 10
    config.agent.min_step_gap_seconds = 60
    assert scheduler.compute_wait(config, 0.0, 0.0, factor=4) == 2400.0


def test_is_llm_failure_discriminates():
    assert scheduler.is_llm_failure(
        {"kind": "error", "error": {"llm_failure": True}}) is True
    assert scheduler.is_llm_failure(
        {"kind": "error", "error": {"llm_failure": False}}) is False
    assert scheduler.is_llm_failure(
        {"kind": "error", "error": {"message": "step_timeout", "llm_failure": False}}) is False
    assert scheduler.is_llm_failure({"kind": "wake_step"}) is False


# --------------------------------------------------------------------------- #
# Long-step: not skipped/killed, resumes after min_step_gap, next_wake_at right
# --------------------------------------------------------------------------- #
def test_long_step_not_skipped_resumes_after_gap(config, data_paths):
    config.agent.mode = "heartbeat"
    config.agent.heartbeat_minutes = 10   # 600s
    config.agent.min_step_gap_seconds = 60

    # One step whose monotonic start=0, end=800 (12+ min > 10 min heartbeat).
    clock = _ScriptedClock([0.0, 800.0])
    wall = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    llm = FakeLLM([_act(), _reflect()])

    infos = []
    info = scheduler.run_scheduler(
        config, data_paths, llm, max_iterations=1,
        sleep=lambda s: None, monotonic=clock, wall_now=lambda: wall,
        on_iteration=infos.append,
    )
    # Step completed (never skipped/killed) and produced a wake_step record.
    assert info["record"]["kind"] == "wake_step"
    # Resumes after exactly min_step_gap (long step path).
    assert info["wait"] == 60.0
    # next_wake_at reflects the real computed next start (wall + 60s).
    st = state_store.read_state(data_paths.state_json)
    assert st["next_wake_at"] == wall.replace(minute=1).isoformat()


def test_next_wake_at_includes_wait(config, data_paths):
    config.agent.mode = "heartbeat"
    config.agent.heartbeat_minutes = 10
    config.agent.min_step_gap_seconds = 60
    clock = _ScriptedClock([0.0, 60.0])  # short step, wait 540
    wall = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    llm = FakeLLM([_act(), _reflect()])
    info = scheduler.run_scheduler(
        config, data_paths, llm, max_iterations=1,
        sleep=lambda s: None, monotonic=clock, wall_now=lambda: wall,
    )
    assert info["wait"] == 540.0
    st = state_store.read_state(data_paths.state_json)
    expected = wall.replace(minute=9)  # +540s = +9 min
    assert st["next_wake_at"] == expected.isoformat()


# --------------------------------------------------------------------------- #
# Circuit breaker: 5 consecutive LLM failures -> interval x4 until a success
# --------------------------------------------------------------------------- #
def test_circuit_breaker_trips_after_threshold_and_resets(config, data_paths):
    config.agent.mode = "heartbeat"
    config.agent.heartbeat_minutes = 10   # 600s
    config.agent.min_step_gap_seconds = 60
    config.agent.consecutive_error_backoff = 5

    # 5 LLM failures (each ACT raises), then a success (act+reflect).
    llm = FakeLLM([
        LLMError("x"), LLMError("x"), LLMError("x"), LLMError("x"), LLMError("x"),
        _act(), _reflect(),
    ])
    # start=end=0 every step so wait == heartbeat*factor.
    clock = _ScriptedClock([0.0])
    wall = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)

    infos = []
    scheduler.run_scheduler(
        config, data_paths, llm, max_iterations=6,
        sleep=lambda s: None, monotonic=clock, wall_now=lambda: wall,
        on_iteration=infos.append,
    )
    # Iterations 1-4: not yet tripped (factor 1 -> wait 600).
    assert [i["factor"] for i in infos[:4]] == [1, 1, 1, 1]
    assert infos[3]["wait"] == 600.0
    # Iteration 5: 5th consecutive failure -> tripped, factor 4 -> wait 2400.
    assert infos[4]["factor"] == 4
    assert infos[4]["wait"] == 2400.0
    # Iteration 6: success resets the breaker.
    assert infos[5]["record"]["kind"] == "wake_step"
    assert infos[5]["factor"] == 1
    assert infos[5]["wait"] == 600.0


# --------------------------------------------------------------------------- #
# Step timeout at a boundary (circuit breaker NOT incremented)
# --------------------------------------------------------------------------- #
def test_step_timeout_at_boundary_preserves_and_not_counted(config, data_paths):
    from soul.agent import loop

    config.agent.step_timeout_minutes = 1  # 60s deadline

    # constructor reads 0.0 (start); the first boundary (before ACT) reads 100.0
    # -> 100 >= 60 -> StepTimeout at that boundary.
    clock = _ScriptedClock([0.0, 100.0])
    controller = StepController(data_paths, config, monotonic=clock)

    llm = FakeLLM([_act(), _reflect()])
    record = loop.run_step(config, data_paths, llm, controller=controller)

    assert record["kind"] == "error"
    assert record["error"]["message"] == "step_timeout"
    # NOT an LLM failure -> circuit breaker will not count it.
    assert scheduler.is_llm_failure(record) is False

    # The next step runs normally.
    llm2 = FakeLLM([_act(), _reflect()])
    rec2 = loop.run_step(config, data_paths, llm2)
    assert rec2["kind"] == "wake_step"


def test_step_timeout_after_act_preserves_partial_note(config, data_paths):
    from soul.agent import loop

    config.agent.step_timeout_minutes = 1
    # monotonic call order: constructor(start)=0, act-boundary=0, tools-boundary
    # =0, reflect-boundary=100 -> trips only at REFLECT, after ACT's note write.
    clock = _ScriptedClock([0.0, 0.0, 0.0, 100.0])
    controller = StepController(data_paths, config, monotonic=clock)
    llm = FakeLLM([_act(topic="kept", content="# kept\n\npartial body"), _reflect()])
    record = loop.run_step(config, data_paths, llm, controller=controller)

    assert record["kind"] == "error"
    assert record["error"]["message"] == "step_timeout"
    # Partial ACT artifact preserved.
    assert record["content_path"] == "notes/step-000001.md"
    assert (data_paths.notes_dir / "step-000001.md").exists()
