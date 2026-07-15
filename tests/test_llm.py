"""Tests for the LLM client: retries/backoff and transcript capture (M1)."""

from __future__ import annotations

import json

import httpx
import pytest

from soul.agent.llm import LLMClient, LLMError, TranscriptRecorder


def _ok_response():
    body = {
        "model": "test-model",
        "choices": [{"message": {"content": "{\"ok\": true}"}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 5},
    }
    return httpx.Response(200, json=body)


def test_success_no_retry():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return _ok_response()

    client = LLMClient(
        base_url="https://x/v1", model="m", api_key=None,
        transport=httpx.MockTransport(handler),
        sleep=lambda s: None,
    )
    resp = client.chat([{"role": "user", "content": "hi"}], json_object=True)
    assert calls["n"] == 1
    assert resp.content == '{"ok": true}'
    assert resp.tokens_in == 3 and resp.tokens_out == 5


def test_retries_then_succeeds_on_500():
    seq = [500, 500, 200]
    slept = []

    def handler(request):
        code = seq.pop(0)
        if code == 200:
            return _ok_response()
        return httpx.Response(code, json={"error": "boom"})

    client = LLMClient(
        base_url="https://x/v1", model="m", api_key=None, max_retries=3,
        transport=httpx.MockTransport(handler),
        sleep=lambda s: slept.append(s),
    )
    resp = client.chat([{"role": "user", "content": "hi"}])
    assert resp.content == '{"ok": true}'
    assert slept == [1, 4]  # backed off before the 2 retries


def test_exhausts_retries_and_raises_on_429():
    slept = []

    def handler(request):
        return httpx.Response(429, json={"error": "rate"})

    client = LLMClient(
        base_url="https://x/v1", model="m", api_key=None, max_retries=3,
        transport=httpx.MockTransport(handler),
        sleep=lambda s: slept.append(s),
    )
    with pytest.raises(LLMError):
        client.chat([{"role": "user", "content": "hi"}])
    assert slept == [1, 4]  # 3 attempts -> 2 backoffs


def test_transcript_recorder_captures_roundtrip(tmp_path):
    path = tmp_path / "step-000001.jsonl"
    recorder = TranscriptRecorder(path)

    def handler(request):
        return _ok_response()

    client = LLMClient(
        base_url="https://x/v1", model="m", api_key=None,
        transport=httpx.MockTransport(handler),
        sleep=lambda s: None,
    )
    client.chat([{"role": "user", "content": "hi"}], recorder=recorder)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["messages"][0]["content"] == "hi"
    assert entry["response"]["choices"][0]["message"]["content"] == '{"ok": true}'


def test_reasoning_field_captured():
    body = {
        "model": "test-model",
        "choices": [{"message": {"content": "hi", "reasoning_content": "because"}}],
        "usage": {},
    }

    def handler(request):
        return httpx.Response(200, json=body)

    client = LLMClient(
        base_url="https://x/v1", model="m", api_key=None,
        transport=httpx.MockTransport(handler),
        sleep=lambda s: None,
    )
    resp = client.chat([{"role": "user", "content": "hi"}])
    assert resp.reasoning == "because"
