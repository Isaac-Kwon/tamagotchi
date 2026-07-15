"""SOUL.md read/write + git commit in the data repo (spec P1/§3).

Role separation (spec P1): only this module writes SOUL.md. Every change is
committed to the data-directory git repo so the "soul's growth history" is
visible as a diff. ``soul_max_chars`` is enforced on write.
"""

from __future__ import annotations

import subprocess

from ..paths import DataPaths, SOUL_SEED


class SoulWriteError(Exception):
    """Raised when a SOUL.md write is rejected (e.g. exceeds size limit)."""


def read_soul(paths: DataPaths) -> str:
    """Return the current SOUL.md text, seeding it if somehow absent."""
    if not paths.soul_md.exists():
        paths.soul_md.write_text(SOUL_SEED, encoding="utf-8")
    return paths.soul_md.read_text(encoding="utf-8")


def _git(paths: DataPaths, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(paths.root), *args],
        capture_output=True,
        text=True,
        check=check,
    )


def _head_commit(paths: DataPaths) -> str | None:
    result = _git(paths, "rev-parse", "HEAD", check=False)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def write_soul(
    paths: DataPaths,
    content: str,
    *,
    soul_max_chars: int,
    commit_message: str = "Update SOUL.md",
) -> str | None:
    """Overwrite SOUL.md and commit it in the data repo.

    Enforces ``soul_max_chars``. Returns the new commit hash, or ``None`` if the
    commit could not be created (e.g. content identical to HEAD — no changes).
    On commit failure the file is still updated (spec P5: file wins, next commit
    picks it up); a single retry is attempted.
    """
    if len(content) > soul_max_chars:
        raise SoulWriteError(
            f"SOUL.md update rejected: {len(content)} chars exceeds limit "
            f"{soul_max_chars}."
        )

    paths.soul_md.write_text(content, encoding="utf-8")

    # Stage and commit just SOUL.md. If nothing changed, git commit fails with a
    # non-zero code; we surface that as "no new commit".
    _git(paths, "add", "SOUL.md", check=False)
    commit = _git(paths, "commit", "-q", "-m", commit_message, check=False)
    if commit.returncode != 0:
        # Retry once (spec P5).
        commit = _git(paths, "commit", "-q", "-m", commit_message, check=False)
        if commit.returncode != 0:
            return None

    return _head_commit(paths)
