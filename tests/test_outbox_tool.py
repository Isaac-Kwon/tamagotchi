"""Tests for the ``observer_request`` ACT tool (outbox emission via dispatch)."""

from __future__ import annotations

import json

from soul.config import ObserverRequestsConfig
from soul.knowledge import tools as ktools
from soul.storage import outbox


def test_dispatch_writes_request_and_returns_op(data_paths):
    res = ktools.dispatch(
        data_paths, "observer_request", {"text": "please install numpy"},
        step_id="step-1",
    )
    body = json.loads(res.content)
    rid = body["left"]
    assert rid == "req-0001"
    assert res.outbox_ops == [{"tool": "observer_request", "id": rid}]

    # The request really landed on disk.
    stored = outbox.list_requests(data_paths)
    assert len(stored) == 1
    assert stored[0]["id"] == rid
    assert stored[0]["text"] == "please install numpy"
    assert stored[0]["step_id"] == "step-1"


def test_dispatch_respects_open_cap(data_paths):
    cfg = ObserverRequestsConfig(max_open=3)
    for i in range(3):
        outbox.append_request(data_paths, f"req {i}", step_id=None)

    res = ktools.dispatch(
        data_paths, "observer_request", {"text": "one more"},
        observer_requests_config=cfg,
    )
    body = json.loads(res.content)
    assert "error" in body
    assert body["error"] == "you already have 3 unanswered requests"
    assert res.outbox_ops == []

    # Nothing new was written.
    assert len(outbox.list_requests(data_paths)) == 3


def test_dispatch_empty_text_errors(data_paths):
    res = ktools.dispatch(data_paths, "observer_request", {"text": "   "})
    body = json.loads(res.content)
    assert body == {"error": "text is required"}
    assert res.outbox_ops == []
    assert outbox.list_requests(data_paths) == []


def test_act_tools_includes_observer_request_by_default():
    names = [t["function"]["name"] for t in ktools.act_tools()]
    assert "observer_request" in names


def test_act_tools_can_omit_observer_request():
    names = [
        t["function"]["name"]
        for t in ktools.act_tools(include_observer_requests=False)
    ]
    assert "observer_request" not in names
