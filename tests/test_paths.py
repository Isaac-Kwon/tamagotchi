"""Tests for data-directory initialization (M0)."""

from __future__ import annotations

import subprocess

from soul.paths import DATA_SUBDIRS, init_data_dir


def test_init_creates_full_tree(tmp_path):
    paths = init_data_dir(tmp_path / "data")
    for sub in DATA_SUBDIRS:
        assert (paths.root / sub).is_dir(), f"missing {sub}"


def test_soul_seed_is_blank_slate(tmp_path):
    paths = init_data_dir(tmp_path / "data")
    text = paths.soul_md.read_text(encoding="utf-8")
    assert text.startswith("# SOUL")
    # Blank-slate: no personality / interest seeds injected.
    lowered = text.lower()
    for banned in ("curious", "interest in", "loves", "enjoys", "personality"):
        assert banned not in lowered


def test_data_gitignore_written(tmp_path):
    paths = init_data_dir(tmp_path / "data")
    ignore = paths.gitignore.read_text(encoding="utf-8")
    for entry in ("state.json", "index/", "control/", "logs/", "agent.lock",
                  "sandbox/", "transcripts/"):
        assert entry in ignore


def test_home_dir_persistent_and_not_ignored(tmp_path):
    """home/ is created and, unlike the ephemeral sandbox/, is NOT git-ignored —
    it holds data the agent accumulates across steps and should be tracked."""
    paths = init_data_dir(tmp_path / "data")
    assert paths.home_dir.is_dir()
    ignore = paths.gitignore.read_text(encoding="utf-8")
    assert "home/" not in ignore


def test_data_git_repo_initialized_with_commit(tmp_path):
    paths = init_data_dir(tmp_path / "data")
    assert paths.git_dir.exists()
    result = subprocess.run(
        ["git", "-C", str(paths.root), "rev-parse", "HEAD"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip()  # a commit exists


def test_init_is_idempotent(tmp_path):
    p1 = init_data_dir(tmp_path / "data")
    p1.soul_md.write_text("# SOUL\n\nedited by agent\n", encoding="utf-8")
    # Re-initializing must not clobber the agent's SOUL.md.
    init_data_dir(tmp_path / "data")
    assert "edited by agent" in p1.soul_md.read_text(encoding="utf-8")
