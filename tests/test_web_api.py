"""API server tests: every endpoint, SSE, chat, inbox, preemption E2E (M6)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from soul.agent import loop
from soul.agent.fake_llm import FakeLLM
from soul.agent.preempt import StepController
from soul.knowledge import wiki
from soul.storage import control, outbox, state as state_store
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


def _patch_state(paths, **fields):
    """Rewrite state.json fields directly (write_state would reset updated_at)."""
    p = paths.state_json
    data = json.loads(p.read_text(encoding="utf-8"))
    data.update(fields)
    p.write_text(json.dumps(data), encoding="utf-8")


def test_state_not_stale_mid_step_continuous(client):
    """A step silently running for minutes is normal, not stale (spec P5).

    In continuous mode the between-step gap is 60s but a real step (LLM +
    tool loop) takes minutes; mid-step must not be reported stale.
    """
    client._config.agent.mode = "continuous"
    now = datetime.now(timezone.utc)
    _patch_state(
        client._paths,
        updated_at=(now - timedelta(minutes=5)).isoformat(),
        next_wake_at=(now - timedelta(minutes=4)).isoformat(),
    )
    body = client.get("/api/state").json()
    assert body["stale"] is False
    assert body["stale_at"] is not None


def test_state_stale_past_step_deadline_continuous(client):
    """Silence beyond next_wake_at + step_timeout means the loop is dead."""
    client._config.agent.mode = "continuous"
    timeout_min = client._config.agent.step_timeout_minutes
    now = datetime.now(timezone.utc)
    _patch_state(
        client._paths,
        updated_at=(now - timedelta(minutes=timeout_min + 20)).isoformat(),
        next_wake_at=(now - timedelta(minutes=timeout_min + 5)).isoformat(),
    )
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
# outbox (observer requests, 4th allowed write)
# --------------------------------------------------------------------------- #
def test_outbox_empty(client):
    assert client.get("/api/outbox").json() == {"requests": []}


def test_outbox_lists_seeded_newest_first(client):
    outbox.append_request(client._paths, "please install numpy", step_id="s1")
    outbox.append_request(client._paths, "fetch this paper", step_id="s2")
    reqs = client.get("/api/outbox").json()["requests"]
    assert [r["text"] for r in reqs] == ["fetch this paper", "please install numpy"]
    assert all(r["status"] == "open" for r in reqs)


def test_outbox_resolve_happy_path(client):
    rid = outbox.append_request(client._paths, "please install numpy")["id"]
    r = client.post(f"/api/outbox/{rid}/resolve",
                    data={"status": "resolved", "note": "done"})
    assert r.status_code == 200
    assert r.json() == {"id": rid, "status": "resolved"}

    req = client.get("/api/outbox").json()["requests"][0]
    assert req["status"] == "resolved"
    assert req["observer_note"] == "done"


def test_outbox_resolve_second_time_409(client):
    rid = outbox.append_request(client._paths, "x")["id"]
    client.post(f"/api/outbox/{rid}/resolve", data={"status": "resolved"})
    r = client.post(f"/api/outbox/{rid}/resolve", data={"status": "declined"})
    assert r.status_code == 409


def test_outbox_resolve_unknown_id_404(client):
    r = client.post("/api/outbox/req-9999/resolve", data={"status": "resolved"})
    assert r.status_code == 404


def test_outbox_resolve_bad_status_422(client):
    rid = outbox.append_request(client._paths, "x")["id"]
    r = client.post(f"/api/outbox/{rid}/resolve", data={"status": "bogus"})
    assert r.status_code == 422


def test_outbox_status_filter(client):
    open_id = outbox.append_request(client._paths, "still open")["id"]
    done_id = outbox.append_request(client._paths, "finished")["id"]
    client.post(f"/api/outbox/{done_id}/resolve", data={"status": "resolved"})

    open_reqs = client.get("/api/outbox", params={"status": "open"}).json()["requests"]
    assert [r["id"] for r in open_reqs] == [open_id]
    done_reqs = client.get("/api/outbox",
                           params={"status": "resolved"}).json()["requests"]
    assert [r["id"] for r in done_reqs] == [done_id]


def test_outbox_bad_status_filter_422(client):
    assert client.get("/api/outbox", params={"status": "bogus"}).status_code == 422


def test_outbox_resolve_with_file_upload(client):
    rid = outbox.append_request(client._paths, "fetch this paper")["id"]
    r = client.post(
        f"/api/outbox/{rid}/resolve",
        data={"status": "resolved", "note": "attached"},
        files={"file": ("paper.txt", b"hello world", "text/plain")},
    )
    assert r.status_code == 200

    saved = client._paths.outbox_attachments_dir / rid / "paper.txt"
    assert saved.exists()
    assert saved.read_bytes() == b"hello world"

    req = client.get("/api/outbox").json()["requests"][0]
    assert req["attachment"] == f"{rid}/paper.txt"


def test_outbox_resolve_oversize_upload_413(client):
    client._config.observer_requests.max_attachment_mb = 1
    rid = outbox.append_request(client._paths, "big file please")["id"]
    r = client.post(
        f"/api/outbox/{rid}/resolve",
        data={"status": "resolved"},
        files={"file": ("big.bin", b"x" * (2 * 1024 * 1024), "application/octet-stream")},
    )
    assert r.status_code == 413
    # No resolution was recorded — the request is still open.
    assert client.get("/api/outbox").json()["requests"][0]["status"] == "open"


def test_outbox_resolve_file_with_ignored_status_422(client):
    rid = outbox.append_request(client._paths, "x")["id"]
    r = client.post(
        f"/api/outbox/{rid}/resolve",
        data={"status": "ignored"},
        files={"file": ("x.txt", b"data", "text/plain")},
    )
    assert r.status_code == 422


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


# --------------------------------------------------------------------------- #
# IP allowlist (web.allowed_networks)
# --------------------------------------------------------------------------- #
def _allowlist_client(seeded, networks, client_addr):
    config, data_paths = seeded
    config.web.allowed_networks = networks
    app = create_app(config, data_paths, llm=FakeLLM())
    return TestClient(app, client=client_addr)


def test_allowlist_permits_listed_network(seeded):
    c = _allowlist_client(seeded, ["192.168.0.0/24"], ("192.168.0.42", 1234))
    assert c.get("/api/state").status_code == 200


def test_allowlist_rejects_outside_network(seeded):
    c = _allowlist_client(seeded, ["192.168.0.0/24"], ("10.0.0.7", 1234))
    r = c.get("/api/state")
    assert r.status_code == 403
    assert "allowed_networks" in r.text


def test_allowlist_covers_static_ui(seeded):
    c = _allowlist_client(seeded, ["192.168.0.0/24"], ("10.0.0.7", 1234))
    assert c.get("/").status_code == 403


def test_allowlist_fail_closed_on_unparseable_client(seeded):
    # Starlette's TestClient default host is the non-IP string "testclient";
    # with an allowlist configured that must be rejected, not waved through.
    c = _allowlist_client(seeded, ["192.168.0.0/24"], ("testclient", 50000))
    assert c.get("/api/state").status_code == 403


def test_empty_allowlist_disables_filtering(seeded):
    c = _allowlist_client(seeded, [], ("10.9.8.7", 1234))
    assert c.get("/api/state").status_code == 200
