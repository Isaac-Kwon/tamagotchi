"""Built-in action definitions (spec P3).

The v1 action space (spec P3): neutral offline verbs plus web exploration. The
descriptions are deliberately neutral one-liners so the action space does not
steer the agent toward any personality (blank-slate philosophy, P2). The caller
shuffles the order every step to avoid position bias.

    free_write        — write freely about anything
    revisit_notes     — read back over notes written earlier
    organize_notes    — tidy or restructure existing notes
    thought_experiment— reason through an imagined scenario
    code_experiment   — write and run a small piece of code
    web_explore       — look something up beyond these notes
    read_inbox        — read what an observer left (listed ONLY when pending)
    rest              — do nothing this step

Self-authored ``skill:<name>`` entries (P8) append here in a later milestone.
:func:`available_actions` is the single assembly point.
"""

from __future__ import annotations

import random
from typing import Any

# name -> neutral one-line description. Order here is irrelevant; callers shuffle.
BUILTIN_ACTIONS: dict[str, str] = {
    "free_write": "write freely about anything",
    "revisit_notes": "read back over notes written earlier",
    "organize_notes": "tidy or restructure existing notes",
    "thought_experiment": "reason through an imagined scenario",
    "code_experiment": "write and run a small piece of code",
    "web_explore": "look something up beyond these notes",
    "rest": "do nothing this step",
}

# Conditional actions — only offered when their precondition holds.
READ_INBOX = ("read_inbox", "read what an observer left for you")

# Prefix for self-authored skills in the action list (spec P8). Neutral framing.
SKILL_PREFIX = "skill:"


def skill_action_name(skill: str) -> str:
    return f"{SKILL_PREFIX}{skill}"


def available_actions(
    *, inbox_pending: bool = False, skills: list[str] | None = None
) -> list[dict[str, str]]:
    """Return the currently available actions as ``{name, description}``.

    ``read_inbox`` is included only when ``inbox_pending`` is true (spec P3).
    Enabled self-authored ``skill:<name>`` entries (spec P8) are appended, listed
    neutrally among the built-ins so the agent is not steered toward or away from
    its own skills.
    """
    actions = [{"name": name, "description": desc} for name, desc in BUILTIN_ACTIONS.items()]
    if inbox_pending:
        actions.append({"name": READ_INBOX[0], "description": READ_INBOX[1]})
    for skill in skills or []:
        actions.append({
            "name": skill_action_name(skill),
            "description": "run something you defined earlier",
        })
    return actions


def shuffled_actions(
    *, inbox_pending: bool = False, skills: list[str] | None = None,
    rng: random.Random | None = None,
) -> list[dict[str, str]]:
    """Available actions with order shuffled every step (spec P2: no position bias)."""
    actions = available_actions(inbox_pending=inbox_pending, skills=skills)
    r = rng or random
    r.shuffle(actions)
    return actions


def is_known_action(
    name: Any, *, inbox_pending: bool = False, skills: list[str] | None = None
) -> bool:
    """True if ``name`` is a currently offerable action."""
    if not isinstance(name, str):
        return False
    if name in BUILTIN_ACTIONS:
        return True
    if name == READ_INBOX[0]:
        return inbox_pending
    if name.startswith(SKILL_PREFIX):
        return name[len(SKILL_PREFIX):] in (skills or [])
    return False
