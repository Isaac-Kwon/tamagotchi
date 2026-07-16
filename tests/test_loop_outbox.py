"""Loop wiring for the observer-request outbox channel (spec P4).

Exercises the full wake step: the ``observer_request`` ACT tool writing a
request, and resolved/declined resolutions surfacing back into the next step's
context, journal record, and state count.
"""

from __future__ import annotations

import json

from soul.agent import loop
from soul.agent.fake_llm import FakeLLM
from soul.agent.llm import LLMResponse
from soul.storage import journal, outbox, state as state_store


def _tool_call(name, args, call_id="c1"):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def _tool_response(*calls):
    raw = {"choices": [{"message": {"content": "", "tool_calls": list(calls)}}]}
    return LLMResponse(content="", raw=raw, model="fake", tool_calls=list(calls))


def _act(action="free_write", topic="t", content="# done\n\nbody"):
    return {"action": action, "topic": topic, "content": content}


def _reflect(**over):
    base = {
        "interest": 6, "interest_delta": "first", "mood": "curious",
        "reason": "r", "decision": "new", "summary": "s",
        "soul_update": {"update": False, "content": "", "reason": ""},
    }
    base.update(over)
    return base


def _act_messages(llm):
    """The messages of the most recent ACT call (json_object without tools)."""
    for call in reversed(llm.calls):
        if not call.get("json_object"):
            return call["messages"]
    return []


def test_tool_call_records_request_and_state(config, data_paths):
    llm = FakeLLM([
        _tool_response(_tool_call("observer_request", {"text": "please install numpy"})),
        _act(),
        _reflect(),
    ])
    record = loop.run_step(config, data_paths, llm)

    assert record["observer_requests"] == ["req-0001"]
    assert record["observer_resolved"] == []

    # The request is on disk with derived status open.
    reqs = outbox.list_requests(data_paths)
    assert len(reqs) == 1
    assert reqs[0]["id"] == "req-0001"
    assert reqs[0]["status"] == "open"

    st = state_store.read_state(data_paths.state_json)
    assert st["open_requests"] == 1


def test_resolution_surfaces_once(config, data_paths):
    # Step 1: leave a request.
    loop.run_step(config, data_paths, FakeLLM([
        _tool_response(_tool_call("observer_request", {"text": "install numpy"})),
        _act(),
        _reflect(),
    ]))

    # Observer resolves it.
    outbox.append_resolution(data_paths, "req-0001", "resolved", note="done")

    # Step 2: plain ACT+REFLECT — the resolution surfaces.
    llm2 = FakeLLM([_act(), _reflect()])
    record2 = loop.run_step(config, data_paths, llm2)

    assert record2["observer_resolved"] == ["req-0001"]
    blob = json.dumps(_act_messages(llm2))
    assert "An observer responded to a request you left" in blob
    assert "install numpy" in blob
    assert "done" in blob

    # Step 3: cursor advanced — nothing surfaces again.
    llm3 = FakeLLM([_act(), _reflect()])
    record3 = loop.run_step(config, data_paths, llm3)
    assert record3["observer_resolved"] == []
    assert "An observer responded" not in json.dumps(_act_messages(llm3))


def test_attachment_copied_into_home(config, data_paths):
    # Step 1: leave a request.
    loop.run_step(config, data_paths, FakeLLM([
        _tool_response(_tool_call("observer_request", {"text": "send me the paper"})),
        _act(),
        _reflect(),
    ]))

    # Observer stages an attachment on disk and resolves with it.
    att_dir = data_paths.outbox_attachments_dir / "req-0001"
    att_dir.mkdir(parents=True, exist_ok=True)
    (att_dir / "x.txt").write_text("hello", encoding="utf-8")
    outbox.append_resolution(
        data_paths, "req-0001", "resolved", note="here", attachment="req-0001/x.txt"
    )

    llm2 = FakeLLM([_act(), _reflect()])
    loop.run_step(config, data_paths, llm2)

    # The file is now readable from the agent's home dir.
    assert (data_paths.home_dir / "attachments" / "req-0001" / "x.txt").is_file()
    # The context names the home-relative path.
    assert "attachments/req-0001/x.txt" in json.dumps(_act_messages(llm2))


def test_ignored_resolution_is_silent(config, data_paths):
    loop.run_step(config, data_paths, FakeLLM([
        _tool_response(_tool_call("observer_request", {"text": "maybe later"})),
        _act(),
        _reflect(),
    ]))

    outbox.append_resolution(data_paths, "req-0001", "ignored")

    llm2 = FakeLLM([_act(), _reflect()])
    record2 = loop.run_step(config, data_paths, llm2)

    assert record2["observer_resolved"] == []
    assert "An observer responded" not in json.dumps(_act_messages(llm2))
