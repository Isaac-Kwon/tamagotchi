"""Action-space tests (M2): read_inbox conditional visibility (spec P3)."""

from __future__ import annotations

import random

from soul.agent import actions


def test_full_v1_action_set_present():
    names = {a["name"] for a in actions.available_actions()}
    assert {
        "free_write",
        "revisit_notes",
        "organize_notes",
        "thought_experiment",
        "code_experiment",
        "web_explore",
        "rest",
    } <= names


def test_read_inbox_only_with_pending():
    without = {a["name"] for a in actions.available_actions(inbox_pending=False)}
    assert "read_inbox" not in without
    with_pending = {a["name"] for a in actions.available_actions(inbox_pending=True)}
    assert "read_inbox" in with_pending


def test_is_known_action_respects_inbox_gate():
    assert actions.is_known_action("free_write") is True
    assert actions.is_known_action("web_explore") is True
    assert actions.is_known_action("read_inbox", inbox_pending=False) is False
    assert actions.is_known_action("read_inbox", inbox_pending=True) is True
    assert actions.is_known_action("not_a_thing") is False


def test_shuffle_preserves_membership():
    rng = random.Random(7)
    shuffled = actions.shuffled_actions(inbox_pending=True, rng=rng)
    assert {a["name"] for a in shuffled} == {
        a["name"] for a in actions.available_actions(inbox_pending=True)
    }
