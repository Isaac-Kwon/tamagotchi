"""Recall-context assembly (spec P1/P2).

Assembles the "what the agent remembers going into this step" block:
    * the current SOUL.md self-description,
    * the last N step summaries (config ``context_recent_steps``),
    * current thread info (topic + how many steps in it so far).

Serendipity (random resurfacing of a past note) and the observer inbox arrive in
M2; clear extension points are marked below so they can be woven in without
restructuring.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..paths import DataPaths
from ..storage import journal
from . import soul


@dataclass
class ThreadInfo:
    """The thread the current step belongs to."""

    thread_id: str | None = None
    topic: str | None = None
    steps_so_far: int = 0
    previous_interest: int | None = None  # last interest rating in this thread


@dataclass
class RecallContext:
    soul_text: str
    recent_steps: list[dict[str, Any]] = field(default_factory=list)
    thread: ThreadInfo = field(default_factory=ThreadInfo)
    serendipity_note: str | None = None  # text of a resurfaced past note (P2)
    serendipity_note_path: str | None = None  # its data-relative path (journal)
    inbox_messages: list[dict[str, Any]] = field(default_factory=list)  # delivered
    resolved_requests: list[dict[str, Any]] = field(default_factory=list)  # outbox (P4)
    skill_notices: list[str] = field(default_factory=list)  # auto-disabled skills (P8)

    def to_block(self) -> str:
        """Render the recall context as a plain-text block for the ACT prompt."""
        parts: list[str] = []
        parts.append("Your self-description (SOUL.md):\n" + self.soul_text.strip())

        if self.recent_steps:
            lines = []
            for step in self.recent_steps:
                summary = step.get("summary") or step.get("topic") or "(no summary)"
                decision = step.get("decision")
                tag = f" [{decision}]" if decision else ""
                lines.append(f"- {step.get('id', '?')}: {summary}{tag}")
            parts.append("Recent steps (oldest first):\n" + "\n".join(lines))
        else:
            parts.append("Recent steps: none yet — this is an early step.")

        if self.thread.topic:
            parts.append(
                f"Current thread: \"{self.thread.topic}\" "
                f"({self.thread.steps_so_far} step(s) so far)."
            )
        else:
            parts.append("Current thread: none — you are free to start anywhere.")

        # --- M2 extension point: serendipity note ------------------------- #
        if self.serendipity_note:
            parts.append("A note you wrote before:\n" + self.serendipity_note.strip())

        # --- M2 extension point: observer inbox --------------------------- #
        if self.inbox_messages:
            lines = [f"- {m.get('text', '')}" for m in self.inbox_messages]
            parts.append("Something an observer left for you:\n" + "\n".join(lines))

        # --- M2 extension point: observer request resolutions ------------- #
        if self.resolved_requests:
            lines = []
            for r in self.resolved_requests:
                text = r.get("text") or ""
                status = r.get("status") or ""
                line = f'- "{text}" — {status}'
                note = r.get("note")
                if note:
                    line += f": {note}"
                attachment = r.get("attachment")
                if attachment:
                    line += f" (a file was left at attachments/{attachment})"
                lines.append(line)
            parts.append(
                "An observer responded to a request you left:\n" + "\n".join(lines)
            )

        # --- M8: notice about your own skills ----------------------------- #
        if self.skill_notices:
            lines = [f"- {n}" for n in self.skill_notices]
            parts.append("Notice about your skills:\n" + "\n".join(lines))

        return "\n\n".join(parts)


def _derive_thread(recent_steps: list[dict[str, Any]]) -> ThreadInfo:
    """Infer the current thread from the most recent step's decision.

    Thread rules (spec P4): deepen keeps the same thread_id; abandon/new start a
    fresh thread next step; shelve sets the topic aside. For M1 we simply carry
    forward the last step's thread when its decision was 'deepen'.
    """
    if not recent_steps:
        return ThreadInfo()

    last = recent_steps[-1]
    decision = last.get("decision")
    if decision == "deepen":
        # Continue the same thread; count how many consecutive steps share it.
        thread_id = last.get("thread_id")
        steps = 0
        prev_interest = None
        for step in reversed(recent_steps):
            if step.get("thread_id") == thread_id:
                steps += 1
                if prev_interest is None and step.get("interest") is not None:
                    prev_interest = step.get("interest")
            else:
                break
        return ThreadInfo(
            thread_id=thread_id,
            topic=last.get("topic"),
            steps_so_far=steps,
            previous_interest=prev_interest,
        )

    # abandon / new / shelve / none -> next step starts fresh.
    return ThreadInfo()


def _pick_serendipity_note(
    paths: DataPaths, rng: random.Random
) -> tuple[str | None, str | None]:
    """Uniformly draw one past note to resurface (spec P2 environmental chance).

    The draw is *topic-neutral*: a note is chosen at random by file, never by
    content, so it supplies path-dependent chance without seeding any theme
    (blank-slate philosophy). Returns ``(text, data_relative_path)`` or
    ``(None, None)`` when there are no notes yet.
    """
    if not paths.notes_dir.exists():
        return None, None
    notes = sorted(p for p in paths.notes_dir.glob("*.md") if p.is_file())
    if not notes:
        return None, None
    chosen: Path = rng.choice(notes)
    try:
        text = chosen.read_text(encoding="utf-8")
    except OSError:
        return None, None
    return text, f"notes/{chosen.name}"


def assemble_context(
    paths: DataPaths,
    *,
    recent_steps_n: int,
    serendipity_rate: float = 0.0,
    rng: random.Random | None = None,
    inbox_messages: list[dict[str, Any]] | None = None,
    resolved_requests: list[dict[str, Any]] | None = None,
    skill_notices: list[str] | None = None,
) -> RecallContext:
    """Build the recall context for the upcoming step.

    ``serendipity_rate`` (spec ``agent.serendipity_rate``, default 0.3 in config)
    is the probability of resurfacing one uniformly-random past note as "a note
    you wrote before". ``inbox_messages`` are observer messages already drained
    from the inbox for this step (spec P4); they are shown under neutral framing.
    """
    soul_text = soul.read_soul(paths)
    recent = journal.tail(paths, recent_steps_n)
    thread = _derive_thread(recent)

    ctx = RecallContext(
        soul_text=soul_text,
        recent_steps=recent,
        thread=thread,
        inbox_messages=list(inbox_messages or []),
        resolved_requests=list(resolved_requests or []),
        skill_notices=list(skill_notices or []),
    )

    r = rng or random
    if serendipity_rate > 0 and r.random() < serendipity_rate:
        text, rel = _pick_serendipity_note(paths, r)
        ctx.serendipity_note = text
        ctx.serendipity_note_path = rel

    return ctx
