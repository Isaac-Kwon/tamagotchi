"""Periodic data-repo autosave — a safety net between daily reports.

journal/ and notes/ are normally committed only as companions of the daily
report (:mod:`.report`). A run that never reaches ``report.time`` (a short
session, a crash, a report failure) would otherwise leave every step of
history uncommitted — against the spec's "one directory importable wholesale"
goal. So every ``agent.autosave_every_steps`` wake steps (0 disables) the
scheduler commits the accumulating history with an ``autosave @ <step_id>``
message.

Scope: only artifacts with no dedicated commit path of their own. SOUL.md,
wiki, skills, and reports keep their own commits and message conventions
(soul.py / wiki.py / skills.py / report.py).
"""

from __future__ import annotations

import re
import subprocess
from typing import Any

from ..paths import DataPaths

# Accumulating history covered by the autosave commit.
AUTOSAVE_PATHS = ("journal", "notes", "home", "inbox", "chat")

_STEP_NUM = re.compile(r"^step-(\d+)$")


def _git(paths: DataPaths, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(paths.root), *args],
        capture_output=True, text=True, check=False,
    )


def is_due(record: dict[str, Any], every_steps: int) -> bool:
    """True when this step record lands on an autosave boundary.

    Both wake steps and error records carry ``step-NNNNNN`` ids, so error
    steps advance toward the boundary too; records without a step id (e.g.
    a scheduler-level crash placeholder) never trigger a save.
    """
    if every_steps <= 0:
        return False
    m = _STEP_NUM.match(str(record.get("id") or ""))
    return m is not None and int(m.group(1)) % every_steps == 0


def maybe_autosave(
    paths: DataPaths, record: dict[str, Any], every_steps: int
) -> str | None:
    """Commit accumulated history every N steps. Returns the commit hash.

    Returns ``None`` when not due or when there was nothing to commit — a
    clean tree makes ``git commit`` fail, which is the normal idle case, not
    an error.
    """
    if not is_due(record, every_steps):
        return None
    existing = [p for p in AUTOSAVE_PATHS if (paths.root / p).exists()]
    if not existing:
        return None
    _git(paths, "add", "--", *existing)
    commit = _git(paths, "commit", "-q", "-m", f"autosave @ {record['id']}")
    if commit.returncode != 0:
        return None
    head = _git(paths, "rev-parse", "HEAD")
    return (head.stdout.strip() or None) if head.returncode == 0 else None
