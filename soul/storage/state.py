"""state.json — the single UI snapshot, written atomically (spec P4/P5).

Atomic replacement: write to a temp file in the same directory then
``os.replace`` (atomic on Windows and POSIX). Reads fall back to a default
snapshot if the file is missing or corrupt, so a partial write never crashes a
reader.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_state() -> dict[str, Any]:
    """A fresh, empty state snapshot (schema per spec P4)."""
    return {
        "status": "idle",  # awake | idle | chatting | error
        "last_step": None,
        "current_thread": None,  # {topic, steps, interest_series}
        "shelved_threads": [],
        "revealed": {"top_threads": [], "stated_vs_revealed_note": None},
        "next_wake_at": None,
        "today_report": None,
        "step_counter": 0,  # monotonically increasing step id source
        "updated_at": _now_iso(),
    }


def read_state(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Read state.json, returning a default snapshot on missing/corrupt file."""
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return default_state()
        return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default_state()


def write_state(path: str | os.PathLike[str], state: dict[str, Any]) -> None:
    """Atomically write ``state`` to state.json (tmp file + os.replace)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    state = dict(state)
    state["updated_at"] = _now_iso()

    tmp = p.with_name(f"{p.name}.tmp-{os.getpid()}")
    tmp.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, p)


def next_step_id(path: str | os.PathLike[str]) -> tuple[str, dict[str, Any]]:
    """Return the next step id and the updated state (counter incremented).

    The state is NOT written here; the caller persists it after the step so the
    counter and the step's other fields are committed together.
    """
    state = read_state(path)
    counter = int(state.get("step_counter", 0)) + 1
    state["step_counter"] = counter
    return f"step-{counter:06d}", state
