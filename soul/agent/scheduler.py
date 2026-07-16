"""Long-running scheduler: heartbeat / continuous modes + daily report (spec P5).

Shape (spec P5)::

    while True:
        check_preempt()      # crash-recovery of a leftover paused step
        check_report()       # idempotent daily report, between every step
        run_step()           # one wake step (never killed for running long)
        maybe_autosave()     # commit journal/notes every N steps (safety net)
        wait()               # until the next start time

**Long-step policy (spec P5).** A step that outruns the heartbeat is normal and
is never skipped or killed for it. The next start is:

    * heartbeat mode: ``max(prev_start + heartbeat, prev_end + min_step_gap)``
    * continuous mode: ``prev_end + min_step_gap``

The hard ``step_timeout_minutes`` deadline is enforced *inside* the step by
:class:`~soul.agent.preempt.StepController`, independently of the heartbeat.

**Circuit breaker (spec P5).** ``consecutive_error_backoff`` consecutive LLM
failures multiply the interval by 4 until a success. Parse failures and step
timeouts are NOT LLM failures and do not count.

``state.json``'s ``next_wake_at`` always reflects the real computed next start so
the UI countdown is accurate.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from ..config import Config
from ..paths import DataPaths
from ..storage import state as state_store
from . import autosave, loop as loop_mod
from . import preempt, report
from .preempt import StepController

CIRCUIT_MULTIPLIER = 4


def is_llm_failure(record: dict[str, Any]) -> bool:
    """True when a step record is an LLM outage/timeout (circuit-breaker input).

    Parse failures and ``step_timeout`` are errors too but are NOT LLM failures
    (spec P5), so they carry ``llm_failure: false`` and never trip the breaker.
    """
    if record.get("kind") != "error":
        return False
    return bool((record.get("error") or {}).get("llm_failure"))


class CircuitBreaker:
    """Counts consecutive LLM failures; trips after a threshold (spec P5)."""

    def __init__(self, threshold: int, *, multiplier: int = CIRCUIT_MULTIPLIER) -> None:
        self.threshold = threshold
        self.multiplier = multiplier
        self.consecutive = 0

    def observe(self, failed: bool) -> None:
        self.consecutive = self.consecutive + 1 if failed else 0

    @property
    def tripped(self) -> bool:
        return self.threshold > 0 and self.consecutive >= self.threshold

    @property
    def factor(self) -> int:
        return self.multiplier if self.tripped else 1


def compute_wait(
    cfg: Config, start_mono: float, end_mono: float, factor: int = 1
) -> float:
    """Seconds to wait after a step ends before the next one starts (spec P5)."""
    gap = cfg.agent.min_step_gap_seconds
    if cfg.agent.mode == "continuous":
        next_start = end_mono + gap * factor
    else:  # heartbeat
        hb = cfg.agent.heartbeat_minutes * 60
        next_start = max(start_mono + hb * factor, end_mono + gap)
    return max(0.0, next_start - end_mono)


def _write_next_wake(paths: DataPaths, next_wake_at: datetime) -> None:
    try:
        st = state_store.read_state(paths.state_json)
        st["next_wake_at"] = next_wake_at.isoformat()
        state_store.write_state(paths.state_json, st)
    except Exception:  # noqa: BLE001 — scheduling metadata must not crash the loop.
        pass


def run_scheduler(
    cfg: Config,
    paths: DataPaths,
    llm: Any,
    *,
    once: bool = False,
    max_iterations: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    wall_now: Callable[[], datetime] | None = None,
    make_controller: Callable[[], StepController] | None = None,
    on_iteration: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any] | None:
    """Run the scheduler loop. Returns the last iteration's info dict.

    The injectable ``sleep`` / ``monotonic`` / ``wall_now`` / ``make_controller``
    / ``on_iteration`` seams keep the loop fully testable without real time.
    """
    wall_now = wall_now or (lambda: datetime.now(timezone.utc))
    breaker = CircuitBreaker(cfg.agent.consecutive_error_backoff)

    # check_preempt(): recover a paused step left by a crashed prior run (P7.5).
    try:
        preempt.recover_paused_step(paths)
    except Exception:  # noqa: BLE001
        pass

    iterations = 0
    last_info: dict[str, Any] | None = None
    while True:
        # check_report(): idempotent daily report, between every step (P5).
        try:
            report.check_report(cfg, paths, llm)
        except Exception:  # noqa: BLE001
            pass

        # run_step(): a long step is never killed for exceeding the heartbeat.
        start = monotonic()
        controller = make_controller() if make_controller else StepController(paths, cfg)
        try:
            record = loop_mod.run_step(cfg, paths, llm, controller=controller)
        except Exception as exc:  # noqa: BLE001 — a crashed step must not kill the loop.
            record = {"kind": "error", "error": {"message": str(exc), "llm_failure": True}}
        end = monotonic()

        # Autosave: commit accumulated journal/notes every N steps — the
        # safety net between daily reports (0 disables).
        try:
            autosave.maybe_autosave(paths, record, cfg.agent.autosave_every_steps)
        except Exception:  # noqa: BLE001 — history saving must not crash the loop.
            pass

        failed = is_llm_failure(record)
        breaker.observe(failed)
        factor = breaker.factor

        wait = compute_wait(cfg, start, end, factor)
        next_wake_at = wall_now() + timedelta(seconds=wait)
        _write_next_wake(paths, next_wake_at)

        iterations += 1
        last_info = {
            "record": record,
            "wait": wait,
            "next_wake_at": next_wake_at,
            "factor": factor,
            "consecutive_failures": breaker.consecutive,
            "iteration": iterations,
        }
        if on_iteration is not None:
            on_iteration(last_info)

        if once or (max_iterations is not None and iterations >= max_iterations):
            return last_info

        sleep(wait)

    return last_info
