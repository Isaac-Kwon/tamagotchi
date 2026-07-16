"""REST + SSE routes (spec P0 API contract, M6).

Every interaction the UI needs is a REST/SSE endpoint here; the web UI is just
one client (a mobile app could use the same API — spec §2.4). The server is
read-only over the data dir except the four allowed writes (inbox pending, chat
logs, control/chat.json, and outbox/resolutions.jsonl (append) + attachment
files under outbox/attachments/ (create-only) via the resolve endpoint), all
funnelled through dedicated modules.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..config import Config
from ..knowledge import wiki
from ..paths import DataPaths
from ..storage import inbox, journal, outbox, state as state_store
from ..agent import report as report_mod
from ..agent import skills as skills_mod
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

    # -- stats --------------------------------------------------------------#
    @router.get("/api/stats")
    def get_stats(timeline: int = 250) -> dict[str, Any]:
        return journal.stats(
            journal.read_all(paths), timeline_limit=max(0, timeline)
        )

    # -- skills -------------------------------------------------------------#
    @router.get("/api/skills")
    def get_skills() -> dict[str, Any]:
        return {
            "skills": skills_mod.list_skills(paths),
            "auto_disable_after_failures": cfg.skills.auto_disable_after_failures,
        }

    # -- config (read-only display fields for the settings popover) ---------#
    @router.get("/api/config")
    def get_config() -> dict[str, Any]:
        # Safe display fields only, grouped by config section. Secrets and
        # deployment/network internals are NEVER exposed here:
        #   llm.api_key, llm.api_key_env, agent.data_dir, web.host, web.port,
        #   web.allowed_networks.
        return {
            "llm": {
                "model": cfg.llm.model,
                "base_url": cfg.llm.base_url,
                "temperature": cfg.llm.temperature,
                "max_output_tokens": cfg.llm.max_output_tokens,
                "timeout_seconds": cfg.llm.timeout_seconds,
                "max_retries": cfg.llm.max_retries,
                "mock": cfg.llm.mock,
            },
            "agent": {
                "mode": cfg.agent.mode,
                "heartbeat_minutes": cfg.agent.heartbeat_minutes,
                "min_step_gap_seconds": cfg.agent.min_step_gap_seconds,
                "step_timeout_minutes": cfg.agent.step_timeout_minutes,
                "context_recent_steps": cfg.agent.context_recent_steps,
                "serendipity_rate": cfg.agent.serendipity_rate,
                "soul_max_chars": cfg.agent.soul_max_chars,
                "autosave_every_steps": cfg.agent.autosave_every_steps,
                "consecutive_error_backoff": cfg.agent.consecutive_error_backoff,
            },
            "chat": {
                "record_default": cfg.chat.record_default,
                "idle_end_seconds": cfg.chat.idle_end_seconds,
                "preempt_max_wait_minutes": cfg.chat.preempt_max_wait_minutes,
            },
            "sandbox": {
                "enabled": cfg.sandbox.enabled,
                "backend": cfg.sandbox.backend,
                "timeout_seconds": cfg.sandbox.timeout_seconds,
            },
            "skills": {
                "enabled": cfg.skills.enabled,
                "timeout_seconds": cfg.skills.timeout_seconds,
                "auto_disable_after_failures": cfg.skills.auto_disable_after_failures,
            },
            "web_actions": {
                "enabled": cfg.web_actions.enabled,
                "http_timeout_seconds": cfg.web_actions.http_timeout_seconds,
                "max_page_kb": cfg.web_actions.max_page_kb,
            },
            "knowledge": {
                "max_tool_rounds": cfg.knowledge.max_tool_rounds,
                "fts_snippet_len": cfg.knowledge.fts_snippet_len,
            },
            "observer_requests": {
                "enabled": cfg.observer_requests.enabled,
                "max_open": cfg.observer_requests.max_open,
                "max_attachment_mb": cfg.observer_requests.max_attachment_mb,
            },
            "report": {
                "time": cfg.report.time,
                "timezone": cfg.report.timezone,
                "language": cfg.report.language,
            },
            "web": {
                "sse_check_ms": cfg.web.sse_check_ms,
            },
        }

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

    # -- outbox (observer requests, 4th allowed write) --------------------- #
    @router.get("/api/outbox")
    def get_outbox(status: str | None = None) -> dict[str, Any]:
        try:
            requests = outbox.list_requests(paths, status=status)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        requests.reverse()  # newest first
        return {"requests": requests}

    @router.post("/api/outbox/{request_id}/resolve")
    async def post_outbox_resolve(
        request_id: str,
        status: str = Form(...),
        note: str | None = Form(None),
        file: UploadFile | None = File(None),
    ) -> dict[str, Any]:
        if status not in outbox.VALID_STATUSES:
            raise HTTPException(
                status_code=422,
                detail=f"status must be one of {list(outbox.VALID_STATUSES)}",
            )

        attachment: str | None = None
        if file is not None and file.filename:
            if status not in ("resolved", "declined"):
                raise HTTPException(
                    status_code=422,
                    detail="a file may only be attached to a resolved or "
                           "declined request",
                )
            name = _safe_attachment_name(file.filename)
            data = await _read_capped(
                file, cfg.observer_requests.max_attachment_mb
            )
            dest_dir = paths.outbox_attachments_dir / request_id
            dest_dir.mkdir(parents=True, exist_ok=True)
            (dest_dir / name).write_bytes(data)
            attachment = f"{request_id}/{name}"

        try:
            outbox.append_resolution(
                paths, request_id, status, note=note, attachment=attachment
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="request not found") from exc
        except outbox.OutboxStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        return {"id": request_id, "status": status}

    return router


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _safe_attachment_name(filename: str) -> str:
    """Reduce an uploaded filename to a safe basename (no path separators or
    null bytes); fall back to ``attachment`` when nothing usable remains."""
    name = os.path.basename(filename.replace("\\", "/")).replace("\x00", "").strip()
    if not name or name in (".", ".."):
        return "attachment"
    return name


async def _read_capped(file: UploadFile, max_mb: int) -> bytes:
    """Read an upload into memory, rejecting anything over ``max_mb`` MB with a
    413 before buffering the whole (potentially unbounded) input."""
    limit = max_mb * 1024 * 1024
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(
                status_code=413,
                detail=f"attachment exceeds {max_mb} MB limit",
            )
        chunks.append(chunk)
    return b"".join(chunks)


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
