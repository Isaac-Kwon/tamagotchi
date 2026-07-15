"""Serendipity + inbox context tests (M2): seeded random draw (spec P2)."""

from __future__ import annotations

import random

from soul.agent import context as context_mod


def _seed_notes(data_paths, names):
    data_paths.notes_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        (data_paths.notes_dir / name).write_text(f"# {name}\n\nbody of {name}", encoding="utf-8")


def test_serendipity_off_by_default(data_paths):
    _seed_notes(data_paths, ["step-000001.md", "step-000002.md"])
    ctx = context_mod.assemble_context(data_paths, recent_steps_n=5, serendipity_rate=0.0)
    assert ctx.serendipity_note is None
    assert ctx.serendipity_note_path is None


def test_serendipity_certain_picks_a_note(data_paths):
    _seed_notes(data_paths, ["step-000001.md", "step-000002.md"])
    rng = random.Random(1234)
    ctx = context_mod.assemble_context(
        data_paths, recent_steps_n=5, serendipity_rate=1.0, rng=rng
    )
    assert ctx.serendipity_note is not None
    assert ctx.serendipity_note_path in ("notes/step-000001.md", "notes/step-000002.md")
    assert "A note you wrote before" in ctx.to_block()


def test_serendipity_is_deterministic_under_seed(data_paths):
    _seed_notes(data_paths, [f"step-{i:06d}.md" for i in range(1, 6)])
    p1 = context_mod.assemble_context(
        data_paths, recent_steps_n=5, serendipity_rate=1.0, rng=random.Random(42)
    ).serendipity_note_path
    p2 = context_mod.assemble_context(
        data_paths, recent_steps_n=5, serendipity_rate=1.0, rng=random.Random(42)
    ).serendipity_note_path
    assert p1 == p2 is not None


def test_serendipity_no_notes_yet(data_paths):
    ctx = context_mod.assemble_context(
        data_paths, recent_steps_n=5, serendipity_rate=1.0, rng=random.Random(0)
    )
    assert ctx.serendipity_note is None


def test_inbox_messages_rendered(data_paths):
    ctx = context_mod.assemble_context(
        data_paths,
        recent_steps_n=5,
        inbox_messages=[{"id": "in-0001", "text": "a gift for you"}],
    )
    block = ctx.to_block()
    assert "Something an observer left" in block
    assert "a gift for you" in block
