"""REST + SSE routes (spec P0 API contract, M6).

Every interaction the UI needs is a REST/SSE endpoint here; the web UI is just
one client (a mobile app could use the same API — spec §2.4). The server is
read-only over the data dir except the three allowed writes (inbox pending, chat
logs, control/chat.json), all funnelled through dedicated modules.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..config import Config
from ..knowledge import wiki
from ..paths import DataPaths
from ..storage import inbox, journal, state as state_store
from ..agent import report as report_mod
from ..agent import soul
from . import events, gitview
from .chat import ChatManager


# --------------------------------------------------------------------------- #
# Request bodies
# --------------------------------------------------------------------------- #
class ChatIn(BaseModel):
    message: str
    session_id: str | None = None
    record: bool | None = None


class ChatEndIn(BaseModel):
    session_id: str


class InboxIn(BaseModel):
    kind: str
    content: str
    url: str | None = None


# --------------------------------------------------------------------------- #
# state snapshot + staleness
# --------------------------------------------------------------------------- #
def _base_interval_seconds(cfg: Config) -> float:
    if cfg.agent.mode == "continuous":
        return float(cfg.agent.min_step_gap_seconds)
    return float(cfg.agent.heartbeat_minutes * 60)


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def stale_deadline(cfg: Config, st: dict[str, Any]) -> datetime | None:
    """Latest instant by which a live agent loop must have written state.json.

    The loop only writes state at step end, and a step is never killed for
    running long (spec P5): after a write it may sleep until ``next_wake_at``
    and then stay silent for a whole step, up to the hard
    ``step_timeout_minutes`` deadline — which itself ends in a write even on
    timeout. Silence within that window is a normal long step (in continuous
    mode the between-step gap is seconds but steps run minutes); only silence
    beyond it is evidence of a dead loop. Returns None when there is no
    timestamp to judge by.
    """
    updated = _parse_ts(st.get("updated_at"))
    if updated is None:
        return None
    anchor = updated + timedelta(seconds=_base_interval_seconds(cfg))
    next_wake = _parse_ts(st.get("next_wake_at"))
    if next_wake is not None and next_wake > anchor:
        anchor = next_wake
    return anchor + timedelta(minutes=cfg.agent.step_timeout_minutes)


def _is_stale(cfg: Config, st: dict[str, Any]) -> bool:
    """No state write by the stale deadline => the loop looks dead (spec P5)."""
    deadline = stale_deadline(cfg, st)
    return deadline is None or datetime.now(timezone.utc) > deadline


def state_snapshot(cfg: Config, paths: DataPaths) -> dict[str, Any]:
    st = dict(state_store.read_state(paths.state_json))
    deadline = stale_deadline(cfg, st)
    st["stale"] = deadline is None or datetime.now(timezone.utc) > deadline
    # stale_at lets the client flip to stale on its own clock: SSE only pushes
    # on state.json changes, so a dead loop sends no event carrying stale=true.
    st["stale_at"] = deadline.isoformat() if deadline is not None else None
    return st


# --------------------------------------------------------------------------- #
# Router factory
# --------------------------------------------------------------------------- #
def build_router(cfg: Config, paths: DataPaths, chat_manager: ChatManager) -> APIRouter:
    router = APIRouter()

    # -- state ------------------------------------------------------------- #
    @router.get("/api/state")
    def get_state() -> dict[str, Any]:
        return state_snapshot(cfg, paths)

    @router.get("/api/events")
    def get_events(request: Request) -> StreamingResponse:
        stream = events.state_event_stream(
            paths.state_json,
            lambda: state_snapshot(cfg, paths),
            check_ms=cfg.web.sse_check_ms,
            is_disconnected=request.is_disconnected,
        )
        return StreamingResponse(stream, media_type="text/event-stream")

    # -- steps ------------------------------------------------------------- #
    @router.get("/api/steps")
    def get_steps(limit: int = 50) -> dict[str, Any]:
        steps = journal.read_all(paths)
        steps.reverse()  # newest first
        if limit and limit > 0:
            steps = steps[:limit]
        return {"steps": steps}

    @router.get("/api/step/{step_id}")
    def get_step(step_id: str) -> dict[str, Any]:
        record = _find_step(paths, step_id)
        if record is None:
            raise HTTPException(status_code=404, detail="step not found")
        content = None
        cp = record.get("content_path")
        if cp:
            fpath = paths.root / cp
            if fpath.exists():
                content = fpath.read_text(encoding="utf-8")
        return {"record": record, "content": content}

    @router.get("/api/step/{step_id}/transcript")
    def get_transcript(step_id: str) -> dict[str, Any]:
        tpath = paths.transcript_file(step_id)
        if not tpath.exists():
            raise HTTPException(status_code=404, detail="transcript not found")
        entries = _read_jsonl(tpath)
        return {"entries": entries}

    # -- soul -------------------------------------------------------------- #
    @router.get("/api/soul")
    def get_soul() -> dict[str, Any]:
        return {
            "content": soul.read_soul(paths),
            "updated_at": gitview.soul_updated_at(paths),
        }

    @router.get("/api/soul/history")
    def get_soul_history() -> dict[str, Any]:
        return {"commits": gitview.soul_history(paths)}

    @router.get("/api/soul/diff/{commit}")
    def get_soul_diff(commit: str) -> dict[str, Any]:
        diff = gitview.soul_diff(paths, commit)
        if diff is None:
            raise HTTPException(status_code=404, detail="commit not found")
        return {"diff": diff}

    # -- reports ----------------------------------------------------------- #
    @router.get("/api/reports")
    def get_reports() -> dict[str, Any]:
        dates: list[str] = []
        if paths.reports_dir.exists():
            dates = sorted(
                (p.stem for p in paths.reports_dir.glob("*.md")), reverse=True
            )
        return {"dates": dates}

    @router.get("/api/report/{date}")
    def get_report(date: str) -> dict[str, Any]:
        fpath = report_mod.report_path(cfg, paths, date)
        if not fpath.exists():
            raise HTTPException(status_code=404, detail="report not found")
        return {"date": date, "content": fpath.read_text(encoding="utf-8")}

    # -- revealed ---------------------------------------------------------- #
    @router.get("/api/revealed")
    def get_revealed() -> dict[str, Any]:
        return journal.revealed_interest(journal.read_all(paths))

    # -- wiki -------------------------------------------------------------- #
    @router.get("/api/wiki/pages")
    def get_wiki_pages() -> dict[str, Any]:
        pages = []
        for p in wiki.list_pages(paths):
            pages.append({
                "slug": p["slug"], "title": p["title"],
                "updated": wiki.page_updated(paths, p["slug"]),
            })
        return {"pages": pages}

    @router.get("/api/wiki/search")
    def get_wiki_search(q: str = "") -> dict[str, Any]:
        results = wiki.search(paths, q, snippet_len=cfg.knowledge.fts_snippet_len)
        return {"results": results}

    @router.get("/api/wiki/page/{slug}")
    def get_wiki_page(slug: str) -> dict[str, Any]:
        page = wiki.read_page(paths, slug)
        if page is None:
            raise HTTPException(status_code=404, detail="page not found")
        return {
            "slug": page["slug"],
            "content": page["body"],
            "backlinks": page["backlinks"],
        }

    @router.get("/api/wiki/graph")
    def get_wiki_graph() -> dict[str, Any]:
        return wiki.graph(paths)

    # -- chat -------------------------------------------------------------- #
    @router.post("/api/chat")
    def post_chat(body: ChatIn) -> dict[str, Any]:
        return chat_manager.send(body.message, body.session_id, body.record)

    @router.post("/api/chat/end")
    def post_chat_end(body: ChatEndIn) -> dict[str, Any]:
        chat_manager.end(body.session_id)
        return {"ok": True}

    @router.get("/api/chat/{session_id}")
    def get_chat(session_id: str) -> dict[str, Any]:
        session = chat_manager.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        return session.to_public()

    # -- inbox ------------------------------------------------------------- #
    @router.post("/api/inbox", status_code=202)
    def post_inbox(body: InboxIn) -> dict[str, Any]:
        if body.kind not in ("message", "gift"):
            raise HTTPException(status_code=422, detail="kind must be message or gift")
        meta: dict[str, Any] = {}
        if body.url:
            meta["url"] = body.url
        record = inbox.append_pending(paths, body.content, kind=body.kind, meta=meta)
        return {"id": record["id"]}

    return router


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _find_step(paths: DataPaths, step_id: str) -> dict[str, Any] | None:
    for s in journal.read_all(paths):
        if s.get("id") == step_id:
            return s
    return None


def _read_jsonl(path) -> list[dict[str, Any]]:
    import json

    out: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return out
