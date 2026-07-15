"""Inter-process signal files under ``data/control/`` (spec P5/P7).

The agent loop and the API server are separate processes sharing the data
directory. They coordinate through two small JSON files, written atomically
(tmp + ``os.replace``) exactly like ``state.json``:

    * ``control/chat.json`` — the chat-preemption bus. The API server sets it
      ``active`` when a chat session is live; the loop watches it at every LLM
      boundary and yields (spec P7).
      Shape: ``{active, session_id, started_at, last_message_at}``.
    * ``control/paused_step.json`` — a snapshot of an in-flight wake step taken
      when the loop yields to a chat, so the step can resume from where it
      stopped (spec P7 step 3).

Only these files live here; everything else the API server touches (inbox
append, chat logs) has its own module. The control dir is gitignored (volatile).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..paths import DataPaths


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, obj: dict[str, Any]) -> None:
    """Write ``obj`` as JSON atomically (tmp file + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


# --------------------------------------------------------------------------- #
# chat.json — the preemption signal
# --------------------------------------------------------------------------- #
def chat_path(paths: DataPaths) -> Path:
    return paths.control_dir / "chat.json"


def read_chat(paths: DataPaths) -> dict[str, Any]:
    """Return the current chat signal, defaulting to an inactive snapshot."""
    data = _read_json(chat_path(paths))
    if not data:
        return {"active": False, "session_id": None, "started_at": None,
                "last_message_at": None}
    return data


def set_chat_active(
    paths: DataPaths,
    session_id: str,
    *,
    started_at: str | None = None,
    last_message_at: str | None = None,
) -> dict[str, Any]:
    """Mark a chat session active (called by the API server on a message)."""
    now = _now_iso()
    existing = read_chat(paths)
    started = started_at or (existing.get("started_at") if existing.get("active") else None) or now
    payload = {
        "active": True,
        "session_id": session_id,
        "started_at": started,
        "last_message_at": last_message_at or now,
    }
    _atomic_write(chat_path(paths), payload)
    return payload


def set_chat_inactive(paths: DataPaths) -> None:
    """Mark the chat bus inactive (chat ended or auto-idle-ended)."""
    _atomic_write(
        chat_path(paths),
        {"active": False, "session_id": None, "started_at": None, "last_message_at": None},
    )


def chat_is_active(chat: dict[str, Any], *, idle_end_seconds: int | None = None) -> bool:
    """True when the chat is active and not past its idle deadline (spec P7.4).

    ``idle_end_seconds`` (if given) treats a session whose ``last_message_at`` is
    older than that many seconds as ended, so the loop resumes even if the API
    server never got to flip the flag.
    """
    if not chat.get("active"):
        return False
    if idle_end_seconds is None:
        return True
    last = chat.get("last_message_at")
    if not last:
        return True
    try:
        ts = datetime.fromisoformat(last)
    except (TypeError, ValueError):
        return True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - ts).total_seconds()
    return age <= idle_end_seconds


# --------------------------------------------------------------------------- #
# paused_step.json — the in-flight step snapshot
# --------------------------------------------------------------------------- #
def paused_step_path(paths: DataPaths) -> Path:
    return paths.control_dir / "paused_step.json"


def write_paused_step(paths: DataPaths, snapshot: dict[str, Any]) -> None:
    """Persist a snapshot of the in-flight step (spec P7 step 3)."""
    _atomic_write(paused_step_path(paths), snapshot)


def read_paused_step(paths: DataPaths) -> dict[str, Any] | None:
    """Return the paused-step snapshot, or None when there is none."""
    return _read_json(paused_step_path(paths))


def clear_paused_step(paths: DataPaths) -> None:
    """Remove the paused-step snapshot (after resume/recovery)."""
    try:
        paused_step_path(paths).unlink()
    except FileNotFoundError:
        pass
