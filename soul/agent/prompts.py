"""English prompt templates — the core of the blank-slate philosophy (spec P2).

Rules enforced here (spec P2 "blank-slate prompt principles"):
    * The system prompt describes only the situation and mechanics.
      NO personality adjectives ("curious", ...), NO example topics.
    * The action list is shuffled every step by the caller (this module never
      hard-codes an order; it renders whatever order it is given).
    * The four decisions each get ONE symmetric, neutral, one-line definition.
    * The interest scale is anchored only at its endpoints (1 / 10), paired with
      a relative anchor (interest_delta) against the previous rating in the
      thread — to counter central-tendency bias.
    * REFLECT JSON field order is deliberate: reason comes BEFORE decision.
    * soul_update defaults to false; true only when something durable emerged.

All identifiers, comments, and prompt text are in English (project rule).
"""

from __future__ import annotations

import json
from typing import Any

# --------------------------------------------------------------------------- #
# Decisions — symmetric, neutral one-line definitions (spec P2).
# Kept parallel in structure so none is framed as preferable.
# --------------------------------------------------------------------------- #
DECISION_DEFINITIONS: dict[str, str] = {
    "deepen": "continue with the current topic in the next step",
    "shelve": "set the current topic aside to possibly return to later",
    "abandon": "drop the current topic and do not plan to return to it",
    "new": "leave the current topic and move to a different one next",
}

MOOD_VALUES: tuple[str, ...] = (
    "neutral",
    "curious",
    "excited",
    "calm",
    "bored",
    "frustrated",
    "tired",
    "proud",
)

DEFAULT_MOOD = "neutral"

# --------------------------------------------------------------------------- #
# System prompt — situation + mechanics only. No seeds of any kind.
# --------------------------------------------------------------------------- #
ACT_SYSTEM_PROMPT = """\
You are an agent that lives on its own. Time passes in discrete steps. On each \
step you choose exactly one action from a given list and carry it out, \
producing a written result. There is no external goal, task, or audience to \
satisfy; what you do with each step is entirely up to you. You keep a private \
record across steps and a file describing yourself that only you may edit. You \
also have a working directory that persists across steps: any code you run \
executes there, and files you write with relative paths remain available to you \
in later steps.

Respond with a single JSON object and nothing else, in this exact shape:
{"action": "<one of the listed actions>", "topic": "<one short line>", \
"content": "<the full result of doing the action, in markdown>"}
"""

REFLECT_SYSTEM_PROMPT = """\
You just finished a step and produced a result. Now assess it for yourself. \
This is a private self-assessment, not a report to anyone.

Rate how strongly you were drawn to what you just did, on a scale from 1 to 10, \
where 1 means "not drawn to it at all" and 10 means "strongly drawn to it". \
The scale is anchored only at these two endpoints.

Also state whether you were drawn to it more, less, or about the same compared \
to the previous time you rated this same topic (interest_delta). Use "first" if \
this is the first time you are rating this topic.

Then decide what to do about this topic next. The options are equally valid:
- deepen: continue with the current topic in the next step
- shelve: set the current topic aside to possibly return to later
- abandon: drop the current topic and do not plan to return to it
- new: leave the current topic and move to a different one next

Write your reason BEFORE stating the decision.

Respond with a single JSON object and nothing else, with fields in this exact \
order:
{"interest": <integer 1-10>, "interest_delta": "more|less|same|first", \
"mood": "<one of: neutral, curious, excited, calm, bored, frustrated, tired, \
proud>", "reason": "<short>", "decision": "deepen|shelve|abandon|new", \
"summary": "<one short line>", "soul_update": {"update": <true|false>, \
"content": "<if true, the full new text of your self-description file>", \
"reason": "<short>"}}

Only set soul_update.update to true when something durable about who you are has \
emerged and should be written into your self-description. When uncertain, the \
default is false.
"""


def render_action_list(actions: list[dict[str, str]]) -> str:
    """Render the (already-shuffled) action list as neutral one-line entries.

    ``actions`` is a list of ``{"name", "description"}`` in the order the caller
    chose (shuffled each step upstream — this function preserves that order).
    """
    lines = [f"- {a['name']}: {a['description']}" for a in actions]
    return "\n".join(lines)


def build_act_messages(
    *,
    context_block: str,
    actions: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Assemble the ACT call messages (system + user)."""
    user = (
        f"{context_block}\n\n"
        "Available actions this step (order is random):\n"
        f"{render_action_list(actions)}\n\n"
        "Choose one action and carry it out now."
    )
    return [
        {"role": "system", "content": ACT_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def build_reflect_messages(
    *,
    act_action: str,
    act_topic: str,
    act_content: str,
    previous_interest: int | None,
) -> list[dict[str, Any]]:
    """Assemble the REFLECT call messages.

    ``previous_interest`` is the last interest rating for this same thread/topic,
    supplied so the model has a concrete comparison basis for interest_delta
    (spec P2). ``None`` means there is no prior rating for this topic.
    """
    if previous_interest is None:
        prior = (
            "You have not rated this topic before, so interest_delta should be "
            '"first".'
        )
    else:
        prior = (
            f"The last time you rated this same topic, your interest was "
            f"{previous_interest}. Compare against that for interest_delta."
        )

    user = (
        f"The action you chose: {act_action}\n"
        f"The topic: {act_topic}\n\n"
        f"What you produced:\n{act_content}\n\n"
        f"{prior}\n\n"
        "Now assess this step as instructed."
    )
    return [
        {"role": "system", "content": REFLECT_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def clamp_interest(value: Any) -> int:
    """Clamp interest to the 1..10 range (spec P2 JSON robustness)."""
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return 1
    return max(1, min(10, n))


def normalize_mood(value: Any) -> tuple[str, str | None]:
    """Normalize mood to the enum; out-of-enum -> 'neutral' with raw preserved.

    Returns ``(mood, raw_or_None)`` — ``raw_or_None`` is the original value when
    it had to be replaced, else ``None``.
    """
    if isinstance(value, str) and value in MOOD_VALUES:
        return value, None
    return DEFAULT_MOOD, (value if value is not None else None)


def normalize_decision(value: Any) -> str:
    """Normalize decision; out-of-enum defaults to 'new' (neutral fallback)."""
    if isinstance(value, str) and value in DECISION_DEFINITIONS:
        return value
    return "new"


def normalize_interest_delta(value: Any) -> str:
    if isinstance(value, str) and value in ("more", "less", "same", "first"):
        return value
    return "first"


CORRECTION_PROMPT = (
    "Your previous message was not valid JSON. Reply with ONLY the JSON object "
    "requested, no prose, no code fences."
)


def to_json_line(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)
