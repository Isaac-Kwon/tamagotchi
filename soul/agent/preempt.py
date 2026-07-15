"""Loop-side chat preemption + step-timeout enforcement (spec P5/P7).

Both concerns are enforced at the *same* points: the boundaries between LLM
calls in a wake step (before ACT, between tool rounds, before REFLECT). The
synchronous loop calls :meth:`StepController.boundary` at each; the controller:

    1. checks the hard step deadline (``step_timeout_minutes``) and raises
       :class:`StepTimeout` on breach — the loop records a ``kind:"error"`` step
       with ``error:"step_timeout"``, preserving partial artifacts, and moves on
       (NOT counted toward the circuit breaker — spec P5);
    2. checks ``control/chat.json``; if a chat is active it snapshots the step to
       ``control/paused_step.json``, sets ``state.status="chatting"``, and polls
       every ``preempt_poll_seconds`` until the chat ends or
       ``preempt_max_wait_minutes`` elapses, then resumes from the same point.

Because the loop blocks inside ``boundary`` while a chat runs, "resume" is simply
"unblock and continue" — the in-flight Python state is never torn down. The
snapshot exists only for crash recovery across a process restart
(:func:`recover_paused_step`).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable

from ..config import Config
from ..paths import DataPaths
from ..storage import control, journal, state as state_store


class StepTimeout(Exception):
    """Raised at a boundary when the step's hard deadline has been exceeded."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class StepController:
    """Enforces the step deadline and chat preemption at LLM-call boundaries."""

    def __init__(
        self,
        paths: DataPaths,
        cfg: Config,
        *,
        preempt_enabled: bool = True,
        deadline_enabled: bool = True,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.paths = paths
        self.cfg = cfg
        self.preempt_enabled = preempt_enabled
        self.deadline_enabled = deadline_enabled
        self._sleep = sleep
        self._monotonic = monotonic

        self.step_id: str | None = None
        self.started_at = _now_iso()
        self.preempted = False

        self._start_mono = monotonic()
        self._deadline_seconds = cfg.agent.step_timeout_minutes * 60

    # -- deadline ----------------------------------------------------------- #
    def _check_deadline(self) -> None:
        if not self.deadline_enabled:
            return
        if self._monotonic() - self._start_mono >= self._deadline_seconds:
            raise StepTimeout("step_timeout")

    # -- preemption --------------------------------------------------------- #
    def _check_preempt(
        self,
        phase: str,
        messages: list[dict[str, Any]],
        tool_rounds_done: int,
        act_result: Any,
    ) -> None:
        if not self.preempt_enabled:
            return
        idle = self.cfg.chat.idle_end_seconds
        chat = control.read_chat(self.paths)
        if not control.chat_is_active(chat, idle_end_seconds=idle):
            return

        # A chat is live: snapshot where we are and yield until it ends.
        control.write_paused_step(
            self.paths,
            {
                "step_id": self.step_id,
                "phase": phase,
                "messages_so_far": messages,
                "tool_rounds_done": tool_rounds_done,
                "act_result": act_result,
                "started_at": self.started_at,
            },
        )
        self._set_status_chatting()
        self.preempted = True

        max_wait = self.cfg.chat.preempt_max_wait_minutes * 60
        poll = max(0.01, float(self.cfg.chat.preempt_poll_seconds))
        wait_start = self._monotonic()
        while True:
            self._sleep(poll)
            chat = control.read_chat(self.paths)
            if not control.chat_is_active(chat, idle_end_seconds=idle):
                break
            if self._monotonic() - wait_start >= max_wait:
                break  # yield ceiling reached: resume, re-yield at next boundary

        control.clear_paused_step(self.paths)

    def _set_status_chatting(self) -> None:
        try:
            st = state_store.read_state(self.paths.state_json)
            st["status"] = "chatting"
            state_store.write_state(self.paths.state_json, st)
        except Exception:  # noqa: BLE001 — status is cosmetic; never break a step.
            pass

    # -- public boundary hook ---------------------------------------------- #
    def boundary(
        self,
        phase: str,
        messages: list[dict[str, Any]] | None = None,
        *,
        tool_rounds_done: int = 0,
        act_result: Any = None,
    ) -> None:
        """Called by the loop at every LLM-call boundary.

        Order matters: the deadline is checked first (a runaway step must stop
        even while a chat is waiting), then chat preemption.
        """
        self._check_deadline()
        self._check_preempt(phase, messages or [], tool_rounds_done, act_result)


# --------------------------------------------------------------------------- #
# Crash recovery (spec P7 step 5)
# --------------------------------------------------------------------------- #
def recover_paused_step(paths: DataPaths) -> dict[str, Any] | None:
    """Handle a ``paused_step.json`` left behind by a crashed loop.

    A mid-step LLM conversation cannot be faithfully reconstructed after a
    process restart, so recovery records the interrupted step as a
    ``kind:"error"`` journal entry (marked ``preempted:true``) and clears the
    snapshot, keeping the loop alive. Returns the recovered snapshot or None.
    """
    snap = control.read_paused_step(paths)
    if not snap:
        return None

    step_id = snap.get("step_id") or "step-unknown"
    record = journal.new_step_record(
        step_id,
        kind="error",
        preempted=True,
        transcript_path=f"transcripts/{step_id}.jsonl",
        error={"phase": snap.get("phase"), "message": "interrupted_by_restart"},
    )
    journal.append_step(paths, record)
    control.clear_paused_step(paths)
    control.set_chat_inactive(paths)
    return snap
