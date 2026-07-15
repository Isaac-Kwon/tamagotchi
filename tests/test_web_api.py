"""API server tests: every endpoint, SSE, chat, inbox, preemption E2E (M6)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from soul.agent import loop
from soul.agent.fake_llm import FakeLLM
from soul.agent.preempt import StepController
from soul.knowledge import wiki
from soul.storage import control, state as state_store
from soul.web.server import create_app


def _act(action="free_write", topic="a topic", content="# Note\n\nbody text"):
    return {"action": action, "topic": topic, "content": content}


def _reflect(**over):
    base = {
        "interest": 7, "interest_delta": "first", "mood": "curious",
        "reason": "engaging", "decision": "deepen", "summary": "wrote a note",
        "soul_update": {"update": False, "content": "", "reason": ""},
    }
    base.update(over)
    return base


def _seed_step(config, data_paths, **reflect_over):
    llm = FakeLLM([_act(), _reflect(**reflect_over)])
    return loop.run_step(config, data_paths, llm)


@pytest.fixture
def seeded(config, data_paths):
    """A data dir with a step, a soul commit, a wiki page, and a report."""
    # Step 1 with a SOUL update -> a soul commit for history/diff.
    llm = FakeLLM([
        _act(),
        _reflect(soul_update={"update": True,
                              "content": "# SOUL\n\nI am becoming a writer.",
                              "reason": "durable"}),
    ])
    loop.run_step(config, data_paths, llm)
    # A wiki page.
    wiki.write_page(data_paths, "first-page",
                    "# First\n\nAbout [[second-page]].", commit=True)
    # A report file.
    (data_paths.reports_dir / "2026-07-15.md").write_text(
        "오늘의 회고입니다.", encoding="utf-8")
    return config, data_paths


@pytest.fixture
def client(seeded):
    config, data_paths = seeded
    chat_llm = FakeLLM()
    app = create_app(config, data_paths, llm=chat_llm)
    c = TestClient(app)
    c._app = app
    c._chat_llm = chat_llm  # let tests script chat replies
    c._paths = data_paths
    c._config = config
    return c


# --------------------------------------------------------------------------- #
# state
# --------------------------------------------------------------------------- #
def test_get_state(client):
    r = client.get("/api/state")
    assert r.status_code == 200
    body = r.json()
    assert "stale" in body
    assert body["last_step"]["id"] == "step-000001"


def test_state_stale_when_old(client):
    # Force an ancient updated_at.
    st = state_store.read_state(client._paths.state_json)
    st["updated_at"] = "2000-01-01T00:00:00+00:00"
    state_store.write_state(client._paths.state_json, st)
    # write_state overwrites updated_at with now, so patch the file directly.
    p = client._paths.state_json
    data = json.loads(p.read_text(encoding="utf-8"))
    data["updated_at"] = "2000-01-01T00:00:00+00:00"
    p.write_text(json.dumps(data), encoding="utf-8")
    assert client.get("/api/state").json()["stale"] is True


# --------------------------------------------------------------------------- #
# steps
# --------------------------------------------------------------------------- #
def test_get_steps_newest_first(client):
    _seed_step(client._config, client._paths)  # step-000002
    r = client.get("/api/steps?limit=50")
    steps = r.json()["steps"]
    assert steps[0]["id"] == "step-000002"  # newest first


def test_get_step_and_content(client):
    r = client.get("/api/step/step-000001")
    assert r.status_code == 200
    body = r.json()
    assert body["record"]["id"] == "step-000001"
    assert "body text" in body["content"]


def test_get_step_404(client):
    assert client.get("/api/step/step-999999").status_code == 404
    assert "detail" in client.get("/api/step/step-999999").json()


def test_get_transcript(client):
    r = client.get("/api/step/step-000001/transcript")
    assert r.status_code == 200
    entries = r.json()["entries"]
    assert len(entries) == 2  # ACT + REFLECT
    assert all(isinstance(e, dict) for e in entries)


def test_get_transcript_404(client):
    assert client.get("/api/step/step-000404/transcript").status_code == 404


# --------------------------------------------------------------------------- #
# soul
# --------------------------------------------------------------------------- #
def test_get_soul(client):
    body = client.get("/api/soul").json()
    assert "writer" in body["content"]
    assert body["updated_at"]


def test_soul_history_and_diff(client):
    commits = client.get("/api/soul/history").json()["commits"]
    assert commits, "expected at least one SOUL.md commit"
    assert {"commit", "ts", "message"} <= set(commits[0])
    diff = client.get(f"/api/soul/diff/{commits[0]['commit']}").json()["diff"]
    assert "SOUL.md" in diff


def test_soul_diff_404(client):
    assert client.get("/api/soul/diff/deadbeef").status_code == 404


# --------------------------------------------------------------------------- #
# reports
# --------------------------------------------------------------------------- #
def test_reports_list_and_get(client):
    dates = client.get("/api/reports").json()["dates"]
    assert "2026-07-15" in dates
    body = client.get("/api/report/2026-07-15").json()
    assert body["date"] == "2026-07-15"
    assert "회고" in body["content"]


def test_report_404(client):
    assert client.get("/api/report/1999-01-01").status_code == 404


# --------------------------------------------------------------------------- #
# revealed
# --------------------------------------------------------------------------- #
def test_revealed(client):
    body = client.get("/api/revealed").json()
    assert "top_threads" in body
    assert "stated_vs_revealed_note" in body


# --------------------------------------------------------------------------- #
# wiki
# --------------------------------------------------------------------------- #
def test_wiki_pages(client):
    pages = client.get("/api/wiki/pages").json()["pages"]
    slugs = {p["slug"] for p in pages}
    assert "first-page" in slugs
    assert all("updated" in p for p in pages)


def test_wiki_search(client):
    results = client.get("/api/wiki/search", params={"q": "About"}).json()["results"]
    assert any(r["slug"] == "first-page" for r in results)


def test_wiki_page_and_404(client):
    body = client.get("/api/wiki/page/first-page").json()
    assert body["slug"] == "first-page"
    assert "second-page" in body["content"]
    assert client.get("/api/wiki/page/nope").status_code == 404


def test_wiki_graph(client):
    graph = client.get("/api/wiki/graph").json()
    assert any(n["id"] == "first-page" for n in graph["nodes"])
    assert any(l["src"] == "first-page" and l["dst"] == "second-page"
               for l in graph["links"])


# --------------------------------------------------------------------------- #
# inbox
# --------------------------------------------------------------------------- #
def test_post_inbox_message(client):
    r = client.post("/api/inbox", json={"kind": "message", "content": "hello there"})
    assert r.status_code == 202
    assert r.json()["id"].startswith("in-")


def test_post_inbox_gift_with_url(client):
    r = client.post("/api/inbox",
                    json={"kind": "gift", "content": "a link", "url": "http://x"})
    assert r.status_code == 202


def test_post_inbox_bad_kind(client):
    assert client.post("/api/inbox",
                       json={"kind": "spam", "content": "x"}).status_code == 422


# --------------------------------------------------------------------------- #
# chat
# --------------------------------------------------------------------------- #
def test_chat_roundtrip_memory_only(client):
    client._chat_llm.enqueue("안녕하세요, 반가워요.")
    r = client.post("/api/chat", json={"message": "hi", "record": False})
    assert r.status_code == 200
    body = r.json()
    sid = body["session_id"]
    assert body["reply"] == "안녕하세요, 반가워요."

    # Session retrievable; two turns; not recorded.
    conv = client.get(f"/api/chat/{sid}").json()
    assert conv["record"] is False
    assert len(conv["turns"]) == 2

    # chat.json was set active by the message (preemption signal).
    assert control.read_chat(client._paths)["active"] is True

    # Nothing persisted to recorded.jsonl.
    assert not (client._paths.chat_dir / "recorded.jsonl").exists()

    # End clears the signal.
    assert client.post("/api/chat/end", json={"session_id": sid}).json()["ok"] is True
    assert control.read_chat(client._paths)["active"] is False


def test_chat_recorded_writes_log_and_inbox(client):
    client._chat_llm.enqueue("기록된 답변입니다.")
    r = client.post("/api/chat", json={"message": "remember this", "record": True})
    sid = r.json()["session_id"]

    recorded = (client._paths.chat_dir / "recorded.jsonl")
    assert recorded.exists()
    lines = recorded.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2  # user + assistant

    # An inbox entry was queued so the next wake sees it.
    from soul.storage import inbox
    pending = inbox.peek_pending(client._paths)
    assert any("remember this" in m.get("text", "") for m in pending)


def test_chat_unknown_session_404(client):
    assert client.get("/api/chat/nonexistent").status_code == 404


# --------------------------------------------------------------------------- #
# SSE
# --------------------------------------------------------------------------- #
def test_sse_endpoint_registered(client):
    """The SSE endpoint is wired into the app (behaviour covered by the unit
    test below; TestClient cannot cleanly tear down an infinite stream)."""
    assert "/api/events" in client._app.openapi()["paths"]


def test_sse_generator_emits_on_state_change(client):
    """The stream yields a fresh event within ~1s of a state.json change."""
    import asyncio

    from soul.web import events
    from soul.web.api import state_snapshot

    paths, config = client._paths, client._config
    config.web.sse_check_ms = 20

    async def drive():
        gen = events.state_event_stream(
            paths.state_json,
            lambda: state_snapshot(config, paths),
            check_ms=config.web.sse_check_ms,
        )
        first = await gen.__anext__()          # initial snapshot
        assert first.startswith("event: state")

        # Change state.json; the next yield must reflect it, within ~1s. Force a
        # distinct mtime so the change is detectable regardless of FS resolution.
        import os
        st = state_store.read_state(paths.state_json)
        st["status"] = "chatting"
        state_store.write_state(paths.state_json, st)
        future = paths.state_json.stat().st_mtime + 10
        os.utime(paths.state_json, (future, future))

        second = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        assert second.startswith("event: state")
        payload = json.loads(second.split("data:", 1)[1].strip())
        assert payload["status"] == "chatting"
        await gen.aclose()

    asyncio.run(drive())


# --------------------------------------------------------------------------- #
# Preemption E2E: API sets chat active -> loop pauses -> API ends -> resume
# --------------------------------------------------------------------------- #
def test_preemption_e2e_via_api(client):
    config, paths = client._config, client._paths
    config.chat.preempt_poll_seconds = 1

    client._chat_llm.enqueue("잠깐 얘기해요.")
    sid = client.post("/api/chat", json={"message": "pause please"}).json()["session_id"]
    assert control.read_chat(paths)["active"] is True

    observed = {}

    def fake_sleep(_seconds):
        # We're polling -> snapshot + status must be set. End the chat via API.
        observed["snapshot"] = control.read_paused_step(paths)
        observed["status"] = state_store.read_state(paths.state_json)["status"]
        client.post("/api/chat/end", json={"session_id": sid})

    controller = StepController(paths, config, sleep=fake_sleep)
    step_llm = FakeLLM([_act(), _reflect()])
    record = loop.run_step(config, paths, step_llm, controller=controller)

    assert observed["snapshot"]["phase"] == "act"
    assert observed["status"] == "chatting"
    assert record["kind"] == "wake_step"
    assert record["preempted"] is True
    assert control.read_paused_step(paths) is None


def test_record_toggle_recorded_true_persists_across_next_wake(client):
    """record=true chat becomes an inbox item the next wake actually delivers."""
    client._chat_llm.enqueue("네, 기억할게요.")
    client.post("/api/chat", json={"message": "please recall X", "record": True})
    client.post("/api/chat/end", json={"session_id":
                                       client.get("/api/state").json().get("x", "")
                                       or "ignored"})
    # Next wake drains the inbox and delivers it.
    rec = _seed_step(client._config, client._paths)
    assert rec["inbox_delivered"], "expected the recorded chat to reach the wake"
