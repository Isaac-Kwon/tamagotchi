"""Tests for the periodic data-repo autosave (safety net between reports)."""

from __future__ import annotations

import subprocess

from soul.agent import autosave, scheduler
from soul.agent.fake_llm import FakeLLM


def _git_log(data_paths) -> str:
    out = subprocess.run(
        ["git", "-C", str(data_paths.root), "log", "--format=%s"],
        capture_output=True, text=True, check=True,
    )
    return out.stdout


def _act(topic="t", content="# n\n\nbody"):
    return {"action": "free_write", "topic": topic, "content": content}


def _reflect():
    return {
        "interest": 6, "interest_delta": "first", "mood": "curious",
        "reason": "r", "decision": "new", "summary": "s",
        "soul_update": {"update": False, "content": "", "reason": ""},
    }


# --------------------------------------------------------------------------- #
# is_due
# --------------------------------------------------------------------------- #
def test_is_due_boundary_math():
    assert autosave.is_due({"id": "step-000020"}, 20)
    assert autosave.is_due({"id": "step-000040"}, 20)
    assert not autosave.is_due({"id": "step-000021"}, 20)


def test_is_due_zero_disables():
    assert not autosave.is_due({"id": "step-000020"}, 0)


def test_is_due_ignores_records_without_step_id():
    assert not autosave.is_due({}, 1)
    assert not autosave.is_due({"id": None}, 1)
    assert not autosave.is_due({"id": "not-a-step"}, 1)


# --------------------------------------------------------------------------- #
# maybe_autosave
# --------------------------------------------------------------------------- #
def test_autosave_commits_journal_and_notes(data_paths):
    (data_paths.journal_dir / "steps-2026-07.jsonl").write_text(
        '{"id": "step-000020"}\n', encoding="utf-8"
    )
    (data_paths.notes_dir / "step-000020.md").write_text("note", encoding="utf-8")

    commit = autosave.maybe_autosave(data_paths, {"id": "step-000020"}, 20)
    assert commit is not None
    assert "autosave @ step-000020" in _git_log(data_paths)


def test_autosave_clean_tree_returns_none(data_paths):
    # Nothing new under the autosaved paths -> no commit, no error.
    assert autosave.maybe_autosave(data_paths, {"id": "step-000020"}, 20) is None


def test_autosave_not_due_returns_none(data_paths):
    (data_paths.notes_dir / "step-000019.md").write_text("note", encoding="utf-8")
    assert autosave.maybe_autosave(data_paths, {"id": "step-000019"}, 20) is None


# --------------------------------------------------------------------------- #
# Scheduler integration
# --------------------------------------------------------------------------- #
def test_scheduler_autosaves_on_boundary(config, data_paths):
    config.agent.autosave_every_steps = 1
    llm = FakeLLM([_act(), _reflect()])
    scheduler.run_scheduler(config, data_paths, llm, once=True, sleep=lambda s: None)
    assert "autosave @ step-000001" in _git_log(data_paths)


def test_scheduler_autosave_disabled(config, data_paths):
    config.agent.autosave_every_steps = 0
    llm = FakeLLM([_act(), _reflect()])
    scheduler.run_scheduler(config, data_paths, llm, once=True, sleep=lambda s: None)
    assert "autosave" not in _git_log(data_paths)
