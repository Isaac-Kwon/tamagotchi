"""OpenAI-compatible chat-completions client (spec P0/P5/P2.5).

Responsibilities:
    * Call an OpenAI-compatible ``/chat/completions`` endpoint via httpx.
    * Retry transient failures with exponential backoff (1s / 4s / 16s, max 3).
    * Support ``response_format={"type": "json_object"}``.
    * Capture *every* LLM round-trip — full request messages, raw response, and
      any ``reasoning_content`` / ``reasoning`` field — to
      ``data/transcripts/<step_id>.jsonl`` (one JSON line per call).

The public :meth:`LLMClient.chat` signature matches the FakeLLM so tests and
``--mock`` runtime can substitute a fake transparently.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import httpx

# Retry backoff schedule in seconds (spec P5: 1s / 4s / 16s, max 3 retries).
BACKOFF_SCHEDULE: tuple[int, ...] = (1, 4, 16)

# HTTP statuses worth retrying (rate limit + transient server errors).
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


@dataclass
class LLMResponse:
    """Normalized result of a chat call."""

    content: str
    raw: dict[str, Any]
    model: str | None = None
    reasoning: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    tool_calls: list[dict[str, Any]] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "model": self.model,
            "reasoning": self.reasoning,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "latency_ms": self.latency_ms,
            "tool_calls": self.tool_calls,
        }


class TranscriptRecorder:
    """Appends one JSON line per LLM round-trip to a step transcript file.

    Shared interface used by both the real client and the FakeLLM so chain-of-
    thought capture (spec P2.5) is identical regardless of backend.
    """

    def __init__(self, path: str | Path | None) -> None:
        self.path = Path(path) if path is not None else None

    def record(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        response: LLMResponse | None,
        error: str | None = None,
        backend: str = "llm",
    ) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "backend": backend,
            "messages": messages,
            "tools": tools,
            "response": response.raw if response is not None else None,
            "normalized": response.as_dict() if response is not None else None,
            "reasoning": response.reasoning if response is not None else None,
            "error": error,
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _extract_reasoning(message: dict[str, Any], raw: dict[str, Any]) -> str | None:
    """Capture reasoning tokens if the provider exposed them (spec P2.5)."""
    for key in ("reasoning_content", "reasoning"):
        val = message.get(key)
        if val:
            return val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)
    # Some providers put reasoning at the top level.
    for key in ("reasoning_content", "reasoning"):
        val = raw.get(key)
        if val:
            return val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)
    return None


class LLMClient:
    """Minimal OpenAI-compatible client with retries and transcript capture."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None,
        timeout_seconds: int = 120,
        max_retries: int = 3,
        temperature: float = 1.0,
        max_output_tokens: int = 2000,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self._transport = transport
        self._sleep = sleep

    # -- public interface (mirrors FakeLLM) --------------------------------- #
    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        json_object: bool = False,
        recorder: TranscriptRecorder | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Perform one chat completion, retrying transient failures.

        ``json_object`` sets ``response_format`` to force JSON output.
        ``recorder`` (if given) captures the full round-trip for observability.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_output_tokens,
        }
        if tools:
            payload["tools"] = tools
        if json_object:
            payload["response_format"] = {"type": "json_object"}
        payload.update(kwargs)

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        url = f"{self.base_url}/chat/completions"
        last_error: Exception | None = None
        started = time.monotonic()

        for attempt in range(self.max_retries):
            try:
                with httpx.Client(
                    timeout=self.timeout_seconds, transport=self._transport
                ) as client:
                    resp = client.post(url, json=payload, headers=headers)
                if resp.status_code in RETRYABLE_STATUS:
                    raise httpx.HTTPStatusError(
                        f"retryable status {resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )
                resp.raise_for_status()
                raw = resp.json()
                result = self._normalize(raw, int((time.monotonic() - started) * 1000))
                if recorder is not None:
                    recorder.record(
                        messages=messages, tools=tools, response=result
                    )
                return result
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                last_error = exc
                if attempt < self.max_retries - 1:
                    delay = BACKOFF_SCHEDULE[min(attempt, len(BACKOFF_SCHEDULE) - 1)]
                    self._sleep(delay)
                    continue
                break

        if recorder is not None:
            recorder.record(
                messages=messages, tools=tools, response=None, error=str(last_error)
            )
        raise LLMError(f"LLM request failed after {self.max_retries} attempts: {last_error}")

    # -- helpers ------------------------------------------------------------ #
    def _normalize(self, raw: dict[str, Any], latency_ms: int) -> LLMResponse:
        choices = raw.get("choices") or [{}]
        message = choices[0].get("message", {}) if choices else {}
        content = message.get("content") or ""
        usage = raw.get("usage") or {}
        return LLMResponse(
            content=content,
            raw=raw,
            model=raw.get("model") or self.model,
            reasoning=_extract_reasoning(message, raw),
            tokens_in=int(usage.get("prompt_tokens", 0) or 0),
            tokens_out=int(usage.get("completion_tokens", 0) or 0),
            latency_ms=latency_ms,
            tool_calls=message.get("tool_calls"),
        )


class LLMError(Exception):
    """Raised when the LLM request ultimately fails after retries."""


# --------------------------------------------------------------------------- #
# Tool-use loop (spec P3.5)
# --------------------------------------------------------------------------- #
@dataclass
class ToolLoopResult:
    """Outcome of the ACT tool-use loop."""

    response: LLMResponse           # the final (non-tool) response to parse
    messages: list[dict[str, Any]]  # full conversation incl. every tool round
    rounds: int                     # number of tool rounds actually taken
    forced_final: bool              # True if max rounds forced a tool-less recall


def _assistant_tool_message(resp: LLMResponse) -> dict[str, Any]:
    """Build the assistant message that carries the model's tool_calls."""
    return {
        "role": "assistant",
        "content": resp.content or None,
        "tool_calls": resp.tool_calls,
    }


def run_tool_loop(
    llm: Any,
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]],
    dispatch: Callable[[str, Any], str],
    recorder: TranscriptRecorder | None = None,
    max_rounds: int = 5,
    on_round: Callable[[list[dict[str, Any]], int], None] | None = None,
) -> ToolLoopResult:
    """Run a small function-calling loop (spec P3.5).

    Each round the model may emit ``tool_calls``; every call is dispatched via
    ``dispatch(name, arguments) -> str`` and its result appended as a ``tool``
    message before re-calling. When the model returns content with no tool calls
    the loop ends. After ``max_rounds`` rounds still requesting tools, a final
    tool-less call forces the model to produce its answer. Every round-trip is
    captured by ``recorder`` (chain-of-thought, spec P2.5).

    ``on_round`` (if given) is invoked with ``(convo, round_index)`` immediately
    before each LLM call — this is the boundary the wake loop uses to enforce the
    step deadline and yield to chat preemption (spec P5/P7). It may block (while a
    chat runs) or raise (on a step timeout); both propagate to the caller.

    ``dispatch`` must never raise — a tool failure should come back as content.
    """
    convo: list[dict[str, Any]] = list(messages)

    for round_i in range(max_rounds):
        if on_round is not None:
            on_round(convo, round_i)
        # Tool rounds do NOT force json_object, or the model could not choose to
        # call a tool instead of answering.
        resp = llm.chat(convo, tools=tools, recorder=recorder)
        if not resp.tool_calls:
            return ToolLoopResult(resp, convo, round_i, forced_final=False)

        convo.append(_assistant_tool_message(resp))
        for call in resp.tool_calls:
            fn = call.get("function") or {}
            content = dispatch(fn.get("name"), fn.get("arguments"))
            convo.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id"),
                    "name": fn.get("name"),
                    "content": content,
                }
            )

    # Rounds exhausted: force a final answer with no tools available.
    if on_round is not None:
        on_round(convo, max_rounds)
    final = llm.chat(convo, json_object=True, recorder=recorder)
    return ToolLoopResult(final, convo, max_rounds, forced_final=True)
