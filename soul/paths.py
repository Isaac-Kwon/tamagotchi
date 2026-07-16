"""Data-directory path helpers and initialization.

The data directory is the agent's "body" (spec P1). It is a *separate git
repository* from the source repo so that it can be imported wholesale into
another AI for diagnosis. Only a subset of the tree is version controlled;
derived/volatile artifacts are ignored via ``data/.gitignore``.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

# Sub-directories of the data tree (spec P1).
DATA_SUBDIRS: tuple[str, ...] = (
    "journal",
    "notes",
    "wiki",
    "index",
    "skills",
    "sandbox",
    "home",
    "reports",
    "inbox",
    "chat",
    "transcripts",
    "control",
    "logs",
)

# Entries NOT committed to the data git repo (spec P1: derived / volatile).
DATA_GITIGNORE = """\
# Derived, volatile, or machine-local — not part of the soul's growth history.
state.json
index/
control/
logs/
agent.lock
sandbox/
transcripts/
"""

# Nearly-empty SOUL.md seed. Blank-slate philosophy (spec P2/§3): NO personality,
# interests, or topic seeds — only a neutral statement of ownership.
SOUL_SEED = """\
# SOUL

This file is owned and edited only by the agent itself.
"""


class DataPaths:
    """Convenience accessor for well-known paths inside the data directory."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()

    # -- top-level files ---------------------------------------------------- #
    @property
    def soul_md(self) -> Path:
        return self.root / "SOUL.md"

    @property
    def state_json(self) -> Path:
        return self.root / "state.json"

    @property
    def agent_lock(self) -> Path:
        return self.root / "agent.lock"

    @property
    def gitignore(self) -> Path:
        return self.root / ".gitignore"

    @property
    def git_dir(self) -> Path:
        return self.root / ".git"

    # -- directories -------------------------------------------------------- #
    @property
    def journal_dir(self) -> Path:
        return self.root / "journal"

    @property
    def notes_dir(self) -> Path:
        return self.root / "notes"

    @property
    def wiki_dir(self) -> Path:
        return self.root / "wiki"

    @property
    def index_dir(self) -> Path:
        return self.root / "index"

    @property
    def skills_dir(self) -> Path:
        return self.root / "skills"

    @property
    def sandbox_dir(self) -> Path:
        return self.root / "sandbox"

    @property
    def home_dir(self) -> Path:
        """Persistent working directory for code the agent runs (P3).

        Unlike ``sandbox/`` (ephemeral scratch, git-ignored), this is the cwd of
        every ``code_experiment`` execution and is *not* git-ignored: files the
        agent writes here (relative paths) survive across steps so it can
        accumulate its own data.
        """
        return self.root / "home"

    @property
    def reports_dir(self) -> Path:
        return self.root / "reports"

    @property
    def inbox_dir(self) -> Path:
        return self.root / "inbox"

    @property
    def chat_dir(self) -> Path:
        return self.root / "chat"

    @property
    def transcripts_dir(self) -> Path:
        return self.root / "transcripts"

    @property
    def control_dir(self) -> Path:
        return self.root / "control"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    # -- derived paths ------------------------------------------------------ #
    def journal_file(self, when: datetime | None = None) -> Path:
        """Monthly-rotated journal file: journal/steps-YYYY-MM.jsonl."""
        when = when or datetime.now(timezone.utc)
        return self.journal_dir / f"steps-{when:%Y-%m}.jsonl"

    def transcript_file(self, step_id: str) -> Path:
        """Per-step transcript file: transcripts/<step_id>.jsonl."""
        return self.transcripts_dir / f"{step_id}.jsonl"

    def note_file(self, name: str) -> Path:
        return self.notes_dir / name

    # -- wiki + derived index (M3) ------------------------------------------ #
    def wiki_file(self, slug: str) -> Path:
        return self.wiki_dir / f"{slug}.md"

    @property
    def wiki_index_db(self) -> Path:
        return self.index_dir / "wiki.sqlite3"

    # -- inbox queue (M2) --------------------------------------------------- #
    @property
    def inbox_pending(self) -> Path:
        return self.inbox_dir / "pending.jsonl"

    @property
    def inbox_delivered(self) -> Path:
        return self.inbox_dir / "delivered.jsonl"

    @property
    def inbox_lock(self) -> Path:
        return self.inbox_dir / "inbox.lock"


# --------------------------------------------------------------------------- #
# Git helpers (subprocess — the data dir has its own repo)
# --------------------------------------------------------------------------- #
def _git(paths: DataPaths, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(paths.root), *args],
        capture_output=True,
        text=True,
        check=check,
    )


def _git_is_repo(paths: DataPaths) -> bool:
    return paths.git_dir.exists()


def init_data_dir(root: str | Path) -> DataPaths:
    """Create the data/ tree (spec P1), seed a blank SOUL.md, and init git.

    Idempotent: existing directories/files are left intact. The initial git
    commit is only made when the repo is first created.
    """
    paths = DataPaths(root)
    paths.root.mkdir(parents=True, exist_ok=True)

    for sub in DATA_SUBDIRS:
        (paths.root / sub).mkdir(exist_ok=True)

    # Blank-slate SOUL.md seed (only written if absent — never overwrite the
    # agent's own edits).
    if not paths.soul_md.exists():
        paths.soul_md.write_text(SOUL_SEED, encoding="utf-8")

    # data/.gitignore controls what is committed (spec P1).
    if not paths.gitignore.exists():
        paths.gitignore.write_text(DATA_GITIGNORE, encoding="utf-8")

    # Initialize the data-only git repo and make the initial commit.
    newly_initialized = not _git_is_repo(paths)
    if newly_initialized:
        _git(paths, "init", "-q")
        # Local identity so commits work even without global git config.
        _git(paths, "config", "user.name", "Soul Agent")
        _git(paths, "config", "user.email", "soul@localhost")
        _git(paths, "add", "-A")
        _git(paths, "commit", "-q", "-m", "Initial data directory")

    return paths
