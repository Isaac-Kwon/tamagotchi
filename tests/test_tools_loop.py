"""Tool-use loop tests (M3): FakeLLM tool_calls incl. max-rounds force (P3.5)."""

from __future__ import annotations

import json
import sys
import types

from soul.agent import loop
from soul.agent.fake_llm import FakeLLM
from soul.agent.llm import LLMResponse, run_tool_loop
from soul.knowledge import tools as ktools
from soul.knowledge import wiki
from soul.storage import journal


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


# --------------------------------------------------------------------------- #
# run_tool_loop unit behaviour
# --------------------------------------------------------------------------- #
def test_tool_loop_dispatches_then_finalizes():
    llm = FakeLLM([
        _tool_response(_tool_call("wiki_write", {"slug": "n", "content": "x"})),
        _act(),  # no tool_calls -> final
    ])
    dispatched = []

    def dispatch(name, args):
        dispatched.append((name, args))
        return json.dumps({"ok": True})

    res = run_tool_loop(llm, [{"role": "user", "content": "go"}],
                        tools=ktools.WIKI_TOOLS, dispatch=dispatch, max_rounds=5)
    assert res.forced_final is False
    assert dispatched and dispatched[0][0] == "wiki_write"
    # The final response carries the ACT JSON.
    assert json.loads(res.response.content)["action"] == "free_write"


def test_tool_loop_forces_termination_at_max_rounds():
    # Every round asks for another tool; the loop must stop and force a final.
    responses = [
        _tool_response(_tool_call("wiki_search", {"query": "q"}, f"c{i}"))
        for i in range(2)
    ]
    responses.append(_act())  # the forced tool-less final call returns this
    llm = FakeLLM(responses)
    calls = []

    def dispatch(name, args):
        calls.append(name)
        return "[]"

    res = run_tool_loop(llm, [{"role": "user", "content": "go"}],
                        tools=ktools.WIKI_TOOLS, dispatch=dispatch, max_rounds=2)
    assert res.forced_final is True
    assert res.rounds == 2
    assert len(calls) == 2  # dispatched once per round, then forced to stop
    # The final forced call used no tools.
    assert llm.calls[-1]["tools"] is None


# --------------------------------------------------------------------------- #
# Full step through the loop: wiki_write side effects land in journal + index
# --------------------------------------------------------------------------- #
def test_step_with_wiki_write_tool_records_ops(config, data_paths):
    llm = FakeLLM([
        _tool_response(_tool_call(
            "wiki_write",
            {"slug": "insight", "content": "# Insight\n\nlinks to [[other]]"},
        )),
        _act(),
        _reflect(),
    ])
    record = loop.run_step(config, data_paths, llm)

    assert record["kind"] == "wake_step"
    assert record["wiki_ops"] == [{"tool": "wiki_write", "slug": "insight"}]

    # The page really exists and is indexed with its backlink.
    assert wiki.read_page(data_paths, "insight") is not None
    assert wiki.backlinks(data_paths, "other") == ["insight"]


def test_step_max_rounds_still_completes(config, data_paths):
    config.knowledge.max_tool_rounds = 2
    llm = FakeLLM([
        _tool_response(_tool_call("wiki_search", {"query": "a"}, "c1")),
        _tool_response(_tool_call("wiki_search", {"query": "b"}, "c2")),
        _act(),        # forced final ACT after rounds exhausted
        _reflect(),
    ])
    record = loop.run_step(config, data_paths, llm)
    assert record["kind"] == "wake_step"
    assert len(journal.read_all(data_paths)) == 1


# --------------------------------------------------------------------------- #
# Web tools dispatch via a mocked webtools module (imported lazily).
# --------------------------------------------------------------------------- #
def test_web_tool_dispatch_uses_lazy_webtools(data_paths, monkeypatch):
    fake = types.ModuleType("soul.agent.webtools")
    fake.web_read = lambda url, max_kb=None: {
        "url": url, "title": "T", "text": "hello", "truncated": False
    }
    fake.web_search = lambda query, max_results=5: [
        {"title": "R", "url": "https://x", "snippet": "s"}
    ]
    fake.arxiv_search = lambda query, max_results=5: []
    monkeypatch.setitem(sys.modules, "soul.agent.webtools", fake)

    res = ktools.dispatch(data_paths, "web_read", {"url": "https://x"})
    assert json.loads(res.content)["text"] == "hello"
    assert res.web_visits == ["https://x"]

    res2 = ktools.dispatch(data_paths, "web_search", {"query": "q"})
    assert json.loads(res2.content)[0]["title"] == "R"
