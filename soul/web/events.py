"""Server-Sent Events — pushes state on every state.json change (spec P0/P4).

The agent loop writes ``state.json`` atomically after each step; the API server
watches its mtime and emits an ``event: state`` with the same JSON as
``GET /api/state`` whenever it changes (plus one initial snapshot on connect).
SSE fits the low-frequency, one-way nature of these updates (spec P0). The poll
interval is ``web.sse_check_ms``.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Awaitable, Callable


def _format_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def state_event_stream(
    state_path,
    snapshot: Callable[[], dict[str, Any]],
    *,
    check_ms: int = 1000,
    is_disconnected: Callable[[], Awaitable[bool]] | None = None,
) -> AsyncIterator[str]:
    """Yield an initial state event, then one on each state.json mtime change.

    ``snapshot()`` returns the payload identical to ``GET /api/state`` (state +
    ``stale``). The loop exits when ``is_disconnected()`` reports the client has
    gone (checked each interval), so the generator never outlives its request.
    """
    interval = max(0.01, check_ms / 1000.0)

    def _mtime() -> float:
        try:
            return state_path.stat().st_mtime
        except OSError:
            return 0.0

    # Capture the baseline BEFORE emitting the initial event: the generator
    # suspends at the yield, so any code after it would not run until the next
    # __anext__ — by which time a change may already have happened and be missed.
    last = _mtime()
    # Initial snapshot so a fresh client immediately has state.
    yield _format_event("state", snapshot())

    while True:
        await asyncio.sleep(interval)
        if is_disconnected is not None and await is_disconnected():
            return
        current = _mtime()
        if current != last:
            last = current
            yield _format_event("state", snapshot())
