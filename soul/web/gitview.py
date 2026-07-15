"""Read-only git views of the data repo for the API (spec P5: web reads only).

SOUL.md is the identity file; its git history is "the soul's growth story"
(spec P1/§3). These helpers expose that history and per-commit diffs without ever
writing to the repo. All functions degrade gracefully (empty result) when the
data dir is not a git repo yet.
"""

from __future__ import annotations

import subprocess
from typing import Any

from ..paths import DataPaths

# Record separator unlikely to appear in a commit subject.
_SEP = "\x1f"


def _git(paths: DataPaths, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(paths.root), *args],
        capture_output=True, text=True, check=False,
    )


def soul_history(paths: DataPaths, *, limit: int = 100) -> list[dict[str, str]]:
    """Commits that touched SOUL.md, newest first: {commit, ts, message}."""
    result = _git(
        paths, "log", f"-{limit}", "--follow",
        f"--format=%H{_SEP}%cI{_SEP}%s", "--", "SOUL.md",
    )
    if result.returncode != 0:
        return []
    out: list[dict[str, str]] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split(_SEP)
        if len(parts) >= 3:
            out.append({"commit": parts[0], "ts": parts[1], "message": parts[2]})
    return out


def commit_exists(paths: DataPaths, commit: str) -> bool:
    if not commit or not commit.isalnum():
        return False
    return _git(paths, "cat-file", "-t", commit).stdout.strip() == "commit"


def soul_diff(paths: DataPaths, commit: str) -> str | None:
    """Unified diff of SOUL.md introduced by ``commit`` (None if unknown)."""
    if not commit_exists(paths, commit):
        return None
    result = _git(paths, "show", commit, "--", "SOUL.md")
    if result.returncode != 0:
        return None
    return result.stdout


def soul_updated_at(paths: DataPaths) -> str | None:
    """ISO timestamp of the last commit that touched SOUL.md (else file mtime)."""
    result = _git(paths, "log", "-1", "--format=%cI", "--", "SOUL.md")
    ts = result.stdout.strip() if result.returncode == 0 else ""
    if ts:
        return ts
    try:
        import datetime
        return datetime.datetime.fromtimestamp(
            paths.soul_md.stat().st_mtime, datetime.timezone.utc
        ).isoformat()
    except OSError:
        return None
