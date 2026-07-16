"""Observer-request channel — the agent's outbound "outbox" (mirror of inbox).

The inbox lets observers leave messages *for* the agent; the outbox is the
mirror image: the agent leaves requests *for* an observer (e.g. "please install
numpy", "I can't reach this paywalled paper"). Storage is split into two
append-only files, each with exactly one writer (the strongest form of the
DESIGN.md §11 single-writer rule):

- ``outbox/requests.jsonl`` is appended **only by the agent loop** (via the
  ``observer_request`` ACT tool): ``{"id", "ts", "step_id", "text"}``.
- ``outbox/resolutions.jsonl`` is appended **only by the web server** (via the
  resolve endpoint): ``{"id", "ts", "status", "note", "attachment"}`` where
  ``status`` is one of ``resolved|declined|ignored|reopened`` and ``attachment``
  is a path relative to ``outbox/attachments/`` (e.g. ``req-0001/paper.pdf``).
- ``outbox/seen.json`` (``{"cursor": N}``) is written **only by the agent loop**;
  it records how many resolution records have already been drained. The web
  layer never rewrites any of these files — status is *derived* by joining
  requests against resolutions, never mutated in place.

A request's status is the **last** resolution record for its id (no record →
``open``; a ``reopened`` record derives back to ``open``). ``resolved`` and
``declined`` are terminal.

Draining is **at-least-once**, like ``inbox.drain``: the cursor is a line count
(valid because ``resolutions.jsonl`` is append-only), advanced atomically after
the surfaced records are handed back. A crash between surfacing and cursor
advance re-surfaces a record — never drops one.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..paths import DataPaths
from .locks import AdvisoryFileLock

# Resolution statuses the observer may append (spec: derived-status model).
VALID_STATUSES = ("resolved", "declined", "ignored", "reopened")
# Statuses a caller may filter list_requests by (derived, not raw).
_FILTER_STATUSES = ("open", "resolved", "declined", "ignored")
_TERMINAL = ("resolved", "declined")


class OutboxStateError(Exception):
    """Raised on an invalid resolution transition (e.g. resolving a terminal
    request, or reopening one that is not currently ignored)."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
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


def _next_outbox_id(existing: list[dict[str, Any]]) -> int:
    """Highest numeric suffix of any ``req-XXXX`` id seen so far, plus one."""
    highest = 0
    for r in existing:
        rid = str(r.get("id") or "")
        if rid.startswith("req-"):
            try:
                highest = max(highest, int(rid[4:]))
            except ValueError:
                continue
    return highest + 1


def _derive_status(last: dict[str, Any] | None) -> str:
    """Derived status from the last resolution record for a request."""
    if last is None:
        return "open"
    status = str(last.get("status") or "")
    if status == "reopened":
        return "open"
    return status or "open"


def _last_by_id(resolutions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map request id -> its last resolution record (chronological input)."""
    last: dict[str, dict[str, Any]] = {}
    for r in resolutions:
        rid = str(r.get("id") or "")
        if rid:
            last[rid] = r
    return last


def append_request(paths: DataPaths, text: str, *, step_id: str | None = None) -> dict[str, Any]:
    """Append one agent request to the outbox (used by the ``observer_request``
    tool). Returns the stored record (with its assigned ``id`` and timestamp)."""
    paths.outbox_dir.mkdir(parents=True, exist_ok=True)
    with AdvisoryFileLock(paths.outbox_lock):
        existing = _read_jsonl(paths.outbox_requests)
        record = {
            "id": f"req-{_next_outbox_id(existing):04d}",
            "ts": _now_iso(),
            "step_id": step_id,
            "text": text,
        }
        with paths.outbox_requests.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def list_requests(paths: DataPaths, *, status: str | None = None) -> list[dict[str, Any]]:
    """Chronological joined view: each request plus its derived ``status`` and,
    when resolved/declined, ``resolved_ts`` / ``observer_note`` / ``attachment``
    (all present but ``None`` otherwise).

    ``status`` optionally filters by derived status (``open|resolved|declined|
    ignored``); an invalid filter raises ``ValueError``.
    """
    if status is not None and status not in _FILTER_STATUSES:
        raise ValueError(f"invalid status filter: {status!r}")

    last = _last_by_id(_read_jsonl(paths.outbox_resolutions))
    out: list[dict[str, Any]] = []
    for req in _read_jsonl(paths.outbox_requests):
        rid = str(req.get("id") or "")
        res = last.get(rid)
        derived = _derive_status(res)
        joined = dict(req)
        joined["status"] = derived
        if derived in _TERMINAL and res is not None:
            joined["resolved_ts"] = res.get("ts")
            joined["observer_note"] = res.get("note")
            joined["attachment"] = res.get("attachment")
        else:
            joined["resolved_ts"] = None
            joined["observer_note"] = None
            joined["attachment"] = None
        if status is None or derived == status:
            out.append(joined)
    return out


def open_requests(paths: DataPaths) -> list[dict[str, Any]]:
    """Convenience: the currently-open requests (derived status ``open``)."""
    return list_requests(paths, status="open")


def append_resolution(paths: DataPaths, request_id: str, status: str, *,
                      note: str | None = None,
                      attachment: str | None = None) -> dict[str, Any]:
    """Append one observer resolution for ``request_id`` (used by the web layer).

    Raises ``ValueError`` for an unknown ``status`` value, ``KeyError`` for an
    unknown request id, and ``OutboxStateError`` for an invalid transition
    (resolving/declining a terminal request, reopening a non-ignored request,
    or ignoring one that is not open). Returns the stored resolution record.
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status!r}")

    paths.outbox_dir.mkdir(parents=True, exist_ok=True)
    with AdvisoryFileLock(paths.outbox_lock):
        known = {str(r.get("id") or "") for r in _read_jsonl(paths.outbox_requests)}
        if request_id not in known:
            raise KeyError(request_id)

        current = _derive_status(
            _last_by_id(_read_jsonl(paths.outbox_resolutions)).get(request_id)
        )
        if not _transition_ok(current, status):
            raise OutboxStateError(
                f"cannot {status} request {request_id} in state {current!r}"
            )

        record = {
            "id": request_id,
            "ts": _now_iso(),
            "status": status,
            "note": note,
            "attachment": attachment,
        }
        with paths.outbox_resolutions.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def _transition_ok(current: str, new: str) -> bool:
    """Whether appending resolution ``new`` is valid given derived ``current``."""
    if new == "reopened":
        return current == "ignored"
    if new == "ignored":
        return current == "open"
    if new in _TERMINAL:  # resolved | declined
        return current in ("open", "ignored")
    return False


def _read_cursor(path: Path) -> int:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return int(data.get("cursor", 0))
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError, TypeError):
        pass
    return 0


def _write_cursor(path: Path, cursor: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    tmp.write_text(json.dumps({"cursor": cursor}), encoding="utf-8")
    os.replace(tmp, path)


def drain_new_resolutions(paths: DataPaths, *, home_dir: Path) -> list[dict[str, Any]]:
    """Return resolution records past the ``seen.json`` cursor that should be
    surfaced to the agent, then advance the cursor.

    Only ``resolved``/``declined`` records are surfaced (as a joined dict with
    the request ``id``/``text`` plus ``status``/``note``/``attachment``);
    ``ignored``/``reopened`` records are skipped silently but still advance the
    cursor. For each surfaced record with an attachment, the file under
    ``outbox/attachments/<attachment>`` is copied into
    ``home_dir/attachments/<req-id>/`` so the agent can open it from a code
    experiment (a missing source file is tolerated — the copy is skipped but the
    record is still surfaced). At-least-once, like ``inbox.drain``.
    """
    all_res = _read_jsonl(paths.outbox_resolutions)
    cursor = _read_cursor(paths.outbox_seen)
    new_res = all_res[cursor:]

    req_text = {
        str(r.get("id") or ""): r.get("text")
        for r in _read_jsonl(paths.outbox_requests)
    }

    surfaced: list[dict[str, Any]] = []
    for res in new_res:
        if res.get("status") not in _TERMINAL:
            continue  # ignored / reopened — silent, but the cursor still moves.
        rid = str(res.get("id") or "")
        attachment = res.get("attachment")
        if attachment:
            _copy_attachment(paths, rid, attachment, home_dir)
        surfaced.append({
            "id": rid,
            "text": req_text.get(rid),
            "status": res.get("status"),
            "note": res.get("note"),
            "attachment": attachment,
        })

    _write_cursor(paths.outbox_seen, len(all_res))
    return surfaced


def _copy_attachment(paths: DataPaths, request_id: str, attachment: str,
                     home_dir: Path) -> None:
    """Copy ``outbox/attachments/<attachment>`` into
    ``home_dir/attachments/<request_id>/`` (best effort; missing source ok)."""
    src = paths.outbox_attachments_dir / attachment
    if not src.is_file():
        return
    dest_dir = Path(home_dir) / "attachments" / request_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest_dir / src.name)
