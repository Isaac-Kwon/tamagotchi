"""Built-in action definitions (spec P3).

For milestone M1 only the neutral offline actions ``free_write`` and ``rest``
exist. The descriptions are deliberately neutral one-liners so the action space
does not steer the agent toward any personality (blank-slate philosophy, P2).

The full v1 action set (revisit_notes, organize_notes, thought_experiment,
code_experiment, web_explore, read_inbox, skill:<name>) arrives in later
milestones; :func:`available_actions` is the extension point that assembles the
list — later milestones append to it here.
"""

from __future__ import annotations

import random
from typing import Any

# name -> neutral one-line description.
BUILTIN_ACTIONS: dict[str, str] = {
    "free_write": "write freely about anything",
    "rest": "do nothing this step",
}


def available_actions(*, inbox_pending: bool = False) -> list[dict[str, str]]:
    """Return the list of currently available actions as {name, description}.

    Extension point (M2+): append conditional actions (e.g. read_inbox only when
    ``inbox_pending``) and enabled ``skill:<name>`` entries here.
    """
    actions = [{"name": name, "description": desc} for name, desc in BUILTIN_ACTIONS.items()]
    return actions


def shuffled_actions(
    *, inbox_pending: bool = False, rng: random.Random | None = None
) -> list[dict[str, str]]:
    """Available actions with order shuffled every step (spec P2: no position bias)."""
    actions = available_actions(inbox_pending=inbox_pending)
    r = rng or random
    r.shuffle(actions)
    return actions


def is_known_action(name: Any) -> bool:
    return isinstance(name, str) and name in BUILTIN_ACTIONS
