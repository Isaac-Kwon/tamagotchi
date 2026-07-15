"""Recorded-chat persistence — ``data/chat/recorded.jsonl`` (spec P7 step 6).

Only chats the user explicitly opts to record are persisted here (and fed to the
next wake via the inbox). Unrecorded chats live only in the API server's memory
and vanish on restart — the UI states this honestly. This module is one of the
three data-dir writes the API server is allowed (spec P5).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ..paths import DataPaths


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_turn(paths: DataPaths, session_id: str, role: str, content: str) -> dict[str, Any]:
    """Append one recorded conversation turn to chat/recorded.jsonl."""
    paths.chat_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": _now_iso(),
        "session_id": session_id,
        "role": role,
        "content": content,
    }
    with (paths.chat_dir / "recorded.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def read_all(paths: DataPaths) -> list[dict[str, Any]]:
    """Return every recorded turn (chronological)."""
    path = paths.chat_dir / "recorded.jsonl"
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out
