"""Journal — append-only JSONL of step records, monthly rotation (spec P4).

Each step is one JSON line in ``journal/steps-YYYY-MM.jsonl``. The full step
record schema (spec P4) is produced by :func:`new_step_record`; fields not yet
implemented in this milestone are present with ``null`` values so downstream
consumers can rely on a stable shape.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..paths import DataPaths


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_step_record(step_id: str, *, ts: str | None = None, **overrides: Any) -> dict[str, Any]:
    """Build a step record with every schema field present (null where unset).

    Schema per spec P4. Keyword ``overrides`` set individual fields.
    """
    record: dict[str, Any] = {
        "id": step_id,
        "ts": ts or _now_iso(),
        "kind": "wake_step",  # wake_step | report | error
        "action": None,
        "topic": None,
        "thread_id": None,
        "content_path": None,
        "interest": None,
        "interest_delta": None,
        "mood": None,
        "reason": None,
        "decision": None,
        "summary": None,
        "soul_updated": False,
        "soul_commit": None,
        "serendipity_note": None,
        "transcript_path": None,
        "wiki_ops": [],
        "web_visits": [],
        "skill_used": None,
        "sandbox_backend": None,
        "preempted": False,
        "inbox_delivered": [],
        "llm": {"model": None, "tokens_in": 0, "tokens_out": 0, "latency_ms": 0},
        "error": None,
    }
    record.update(overrides)
    return record


def append_step(paths: DataPaths, record: dict[str, Any]) -> Path:
    """Append one step record as a JSON line to the current monthly journal."""
    when = datetime.now(timezone.utc)
    path = paths.journal_file(when)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return path


def _iter_journal_files(paths: DataPaths) -> list[Path]:
    """All journal files, chronologically ordered by their YYYY-MM name."""
    if not paths.journal_dir.exists():
        return []
    return sorted(paths.journal_dir.glob("steps-*.jsonl"))


def read_all(paths: DataPaths) -> list[dict[str, Any]]:
    """Read every step record across all monthly files, in chronological order."""
    records: list[dict[str, Any]] = []
    for f in _iter_journal_files(paths):
        for raw in f.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                records.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
    return records


def tail(paths: DataPaths, n: int) -> list[dict[str, Any]]:
    """Return the last ``n`` step records across monthly files (chronological)."""
    if n <= 0:
        return []
    records = read_all(paths)
    return records[-n:]
