"""Tests for prompt building + normalization helpers, and blank-slate rules (M1)."""

from __future__ import annotations

from soul.agent import prompts


def test_clamp_interest_bounds():
    assert prompts.clamp_interest(0) == 1
    assert prompts.clamp_interest(11) == 10
    assert prompts.clamp_interest(5) == 5
    assert prompts.clamp_interest("7") == 7
    assert prompts.clamp_interest("garbage") == 1


def test_normalize_mood():
    assert prompts.normalize_mood("curious") == ("curious", None)
    mood, raw = prompts.normalize_mood("weird")
    assert mood == "neutral" and raw == "weird"


def test_normalize_decision_and_delta():
    assert prompts.normalize_decision("deepen") == "deepen"
    assert prompts.normalize_decision("nope") == "new"
    assert prompts.normalize_interest_delta("more") == "more"
    assert prompts.normalize_interest_delta("bogus") == "first"


def test_reflect_field_order_reason_before_decision():
    """Spec P2: reason must be prompted before decision."""
    sys_prompt = prompts.REFLECT_SYSTEM_PROMPT
    assert sys_prompt.index('"reason"') < sys_prompt.index('"decision"')
    assert "BEFORE" in sys_prompt


def test_system_prompt_has_no_personality_seeds():
    """Blank-slate: no personality adjectives or example topics in ACT system."""
    text = prompts.ACT_SYSTEM_PROMPT.lower()
    for banned in ("curious", "creative", "playful", "for example", "such as"):
        assert banned not in text


def test_interest_scale_anchored_only_at_endpoints():
    text = prompts.REFLECT_SYSTEM_PROMPT
    assert "1 to 10" in text
    assert "not drawn to it at all" in text
    assert "strongly drawn to it" in text


def test_build_act_messages_includes_actions():
    actions = [
        {"name": "free_write", "description": "write freely about anything"},
        {"name": "rest", "description": "do nothing this step"},
    ]
    msgs = prompts.build_act_messages(context_block="CTX", actions=actions)
    assert msgs[0]["role"] == "system"
    assert "free_write" in msgs[1]["content"]
    assert "CTX" in msgs[1]["content"]


def test_reflect_previous_interest_supplied():
    msgs = prompts.build_reflect_messages(
        act_action="free_write", act_topic="t", act_content="c",
        previous_interest=7,
    )
    assert "7" in msgs[1]["content"]
    msgs_first = prompts.build_reflect_messages(
        act_action="free_write", act_topic="t", act_content="c",
        previous_interest=None,
    )
    assert "first" in msgs_first[1]["content"].lower()
