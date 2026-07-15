"""FakeLLM — a drop-in substitute for :class:`LLMClient` (spec P10).

It exposes the same ``chat(messages, tools=None, ...)`` interface and returns
:class:`LLMResponse` objects, so the wake loop, ``--mock`` runtime, and tests
all drive it identically. Behaviour is a queue of scripted responses, each
consumed by one ``chat`` call.

A queue item may be:
    * ``dict``  -> serialized to JSON and returned as the message content
      (the common case: an ACT or REFLECT JSON object),
    * ``str``   -> returned verbatim as content (used to script broken JSON or
      JSON wrapped in prose for the robustness tests),
    * ``LLMResponse`` -> returned as-is (full control, e.g. tool_calls),
    * ``Exception`` -> raised (to script LLM failures).

Every round-trip is still written to the transcript recorder when one is passed,
so chain-of-thought capture (spec P2.5) is exercised under mock too.
"""

from __future__ import annotations

import json
from typing import Any

from .llm import LLMResponse, TranscriptRecorder


def _default_reflect() -> dict[str, Any]:
    return {
        "interest": 5,
        "interest_delta": "first",
        "mood": "neutral",
        "reason": "A neutral default reflection.",
        "decision": "new",
        "summary": "A default step.",
        "soul_update": {"update": False, "content": "", "reason": ""},
    }


def _looks_like_reflect(messages: list[dict[str, Any]]) -> bool:
    """Heuristic: a REFLECT call's system prompt asks for a self-assessment."""
    for msg in messages:
        if msg.get("role") == "system" and "interest_delta" in (msg.get("content") or ""):
            return True
    return False


def _default_act() -> dict[str, Any]:
    return {
        "action": "free_write",
        "topic": "a default topic",
        "content": "# Default\n\nSome default written output.",
    }


class FakeLLM:
    """Scripted LLM. Pass ``responses`` as a list of queue items (see module doc)."""

    def __init__(self, responses: list[Any] | None = None) -> None:
        self._queue: list[Any] = list(responses or [])
        self.calls: list[dict[str, Any]] = []  # record of each chat() invocation

    def enqueue(self, *items: Any) -> "FakeLLM":
        self._queue.extend(items)
        return self

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        json_object: bool = False,
        recorder: TranscriptRecorder | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        self.calls.append({"messages": messages, "tools": tools, "json_object": json_object})

        if self._queue:
            item = self._queue.pop(0)
        else:
            # No scripted response: infer whether this is an ACT or REFLECT call
            # from the prompt so a bare --mock run yields a representative step.
            item = _default_reflect() if _looks_like_reflect(messages) else _default_act()

        if isinstance(item, Exception):
            if recorder is not None:
                recorder.record(
                    messages=messages, tools=tools, response=None,
                    error=str(item), backend="fake",
                )
            raise item

        response = self._to_response(item)
        if recorder is not None:
            recorder.record(
                messages=messages, tools=tools, response=response, backend="fake"
            )
        return response

    def _to_response(self, item: Any) -> LLMResponse:
        if isinstance(item, LLMResponse):
            return item
        if isinstance(item, dict):
            content = json.dumps(item, ensure_ascii=False)
        else:
            content = str(item)
        raw = {
            "choices": [{"message": {"content": content}}],
            "model": "fake-model",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        }
        return LLMResponse(
            content=content,
            raw=raw,
            model="fake-model",
            reasoning=None,
            tokens_in=0,
            tokens_out=0,
            latency_ms=0,
        )
