"""Chat sessions handled directly by the API server (spec P0/P7).

The API server answers chats itself by calling the LLM directly (SOUL.md +
recent steps + the session's turns), so the user never waits on the agent loop.
Starting a session writes ``control/chat.json`` active, which the loop watches
and yields to (preemption, spec P7). Recording is the user's choice:

    * ``record=false`` (default): the session lives only in server memory and is
      lost on restart — the UI says so honestly;
    * ``record=true``: turns are appended to ``chat/recorded.jsonl`` AND an inbox
      entry is queued so the next wake sees what was said ("memory" is only what
      was recorded, spec P7 step 6).

The session store is in-memory (per API-server process). This module and the
inbox/control writes, plus the outbox resolve endpoint (outbox/resolutions.jsonl
append + attachment files under outbox/attachments/), are the only data-dir
writes the API server performs.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..config import Config
from ..paths import DataPaths
from ..storage import control, inbox, journal
from ..agent import soul
from . import chatlog

_CHAT_SYSTEM = """\
You are an agent that lives on its own, spending your time on whatever draws \
you. Someone is talking with you now. Your self-description and a summary of \
what you have been doing lately follow. Reply as yourself, in the language the \
other person is using. You are free to engage or not — there is no script.
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ChatSession:
    id: str
    record: bool
    started_at: str = field(default_factory=_now_iso)
    last_message_at: str = field(default_factory=_now_iso)
    turns: list[dict[str, Any]] = field(default_factory=list)

    def to_public(self) -> dict[str, Any]:
        return {"turns": self.turns, "record": self.record}


def build_chat_messages(
    soul_text: str, recent_steps: list[dict[str, Any]], turns: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """System (SOUL + recent activity) + the conversation turns so far."""
    ctx = ["Your self-description (SOUL.md):", soul_text.strip(), ""]
    if recent_steps:
        ctx.append("Recently you have been doing:")
        for s in recent_steps:
            summ = s.get("summary") or s.get("topic") or "(no summary)"
            ctx.append(f"- {summ}")
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _CHAT_SYSTEM + "\n\n" + "\n".join(ctx)},
    ]
    for t in turns:
        messages.append({"role": t["role"], "content": t["content"]})
    return messages


class ChatManager:
    """In-memory chat sessions + the LLM call + preemption/record side effects."""

    def __init__(self, paths: DataPaths, cfg: Config, llm: Any) -> None:
        self.paths = paths
        self.cfg = cfg
        self.llm = llm
        self.sessions: dict[str, ChatSession] = {}

    def get(self, session_id: str) -> ChatSession | None:
        return self.sessions.get(session_id)

    def send(
        self, message: str, session_id: str | None, record: bool | None
    ) -> dict[str, Any]:
        """Handle one chat message; returns ``{session_id, reply}``."""
        session = self.sessions.get(session_id) if session_id else None
        if session is None:
            rec = self.cfg.chat.record_default if record is None else bool(record)
            session = ChatSession(id=uuid.uuid4().hex, record=rec)
            self.sessions[session.id] = session
        elif record is not None:
            session.record = bool(record)  # a later toggle updates the session

        now = _now_iso()
        session.last_message_at = now
        session.turns.append({"role": "user", "content": message, "ts": now})

        # Signal the loop that a chat is live (preemption bus, spec P7).
        control.set_chat_active(
            self.paths, session.id,
            started_at=session.started_at, last_message_at=now,
        )

        reply = self._answer(session)
        session.turns.append(
            {"role": "assistant", "content": reply, "ts": _now_iso()}
        )

        if session.record:
            chatlog.append_turn(self.paths, session.id, "user", message)
            chatlog.append_turn(self.paths, session.id, "assistant", reply)
            # Queue what the observer said so the next wake can see it.
            inbox.append_pending(
                self.paths, message, kind="message",
                meta={"source": "chat", "session_id": session.id},
            )

        return {"session_id": session.id, "reply": reply}

    def _answer(self, session: ChatSession) -> str:
        soul_text = soul.read_soul(self.paths)
        recent = journal.tail(self.paths, self.cfg.agent.context_recent_steps)
        turns = [{"role": t["role"], "content": t["content"]} for t in session.turns]
        messages = build_chat_messages(soul_text, recent, turns)
        try:
            resp = self.llm.chat(messages)
        except Exception:  # noqa: BLE001 — a chat failure must not 500 the caller.
            return "(I could not respond just now.)"
        return (resp.content or "").strip()

    def end(self, session_id: str) -> bool:
        """End a session and clear the preemption signal. Returns True always."""
        control.set_chat_inactive(self.paths)
        return True
