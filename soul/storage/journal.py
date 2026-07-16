"""Journal — append-only JSONL of step records, monthly rotation (spec P4).

Each step is one JSON line in ``journal/steps-YYYY-MM.jsonl``. The full step
record schema (spec P4) is produced by :func:`new_step_record`; fields not yet
implemented in this milestone are present with ``null`` values so downstream
consumers can rely on a stable shape.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..paths import DataPaths


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_step_record(step_id: str, *, ts: str | None = None, **overrides: Any) -> dict[str, Any]:
    """Build a step record with every schema field present (null where unset).

    Schema per spec P4. Keyword ``overrides`` set individual fields.
    """
    record: dict[str, Any] = {
        "id": step_id,
        "ts": ts or _now_iso(),
        "kind": "wake_step",  # wake_step | report | error
        "action": None,
        "topic": None,
        "thread_id": None,
        "content_path": None,
        "interest": None,
        "interest_delta": None,
        "mood": None,
        "reason": None,
        "decision": None,
        "summary": None,
        "soul_updated": False,
        "soul_commit": None,
        "serendipity_note": None,
        "transcript_path": None,
        "wiki_ops": [],
        "web_visits": [],
        "skill_used": None,
        "sandbox_backend": None,
        "preempted": False,
        "inbox_delivered": [],
        "observer_requests": [],
        "observer_resolved": [],
        "llm": {"model": None, "tokens_in": 0, "tokens_out": 0, "latency_ms": 0},
        "error": None,
    }
    record.update(overrides)
    return record


def append_step(paths: DataPaths, record: dict[str, Any]) -> Path:
    """Append one step record as a JSON line to the current monthly journal."""
    when = datetime.now(timezone.utc)
    path = paths.journal_file(when)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return path


def _iter_journal_files(paths: DataPaths) -> list[Path]:
    """All journal files, chronologically ordered by their YYYY-MM name."""
    if not paths.journal_dir.exists():
        return []
    return sorted(paths.journal_dir.glob("steps-*.jsonl"))


def read_all(paths: DataPaths) -> list[dict[str, Any]]:
    """Read every step record across all monthly files, in chronological order."""
    records: list[dict[str, Any]] = []
    for f in _iter_journal_files(paths):
        for raw in f.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                records.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
    return records


def tail(paths: DataPaths, n: int) -> list[dict[str, Any]]:
    """Return the last ``n`` step records across monthly files (chronological)."""
    if n <= 0:
        return []
    records = read_all(paths)
    return records[-n:]


# --------------------------------------------------------------------------- #
# Revealed interest — pure derivation from journal steps (spec P2)
# --------------------------------------------------------------------------- #
def revealed_interest(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive *revealed* interest signals from journal steps (pure function).

    Self-reported ``interest`` is a *stated* signal prone to positive bias and
    confabulation. The true signal is behavioural and accumulates in the record
    (spec P2). This computes it without any LLM involvement:

        * thread duration        — how many steps each thread ran,
        * shelve-then-return     — how often a shelved topic was actually returned to,
        * topic recurrence       — how often the same topic reappears.

    Not stored anywhere; computed on read. ``steps`` is a chronological list of
    step records (as produced by :func:`read_all` / :func:`tail`).
    """
    threads: dict[str, dict[str, Any]] = {}
    topic_counts: Counter[str] = Counter()
    shelved_open: dict[str, int] = {}  # topic -> outstanding shelve count
    returns: Counter[str] = Counter()  # topic -> times returned to after a shelve
    interests: list[int] = []

    for step in steps:
        if step.get("kind") != "wake_step":
            continue
        thread_id = step.get("thread_id")
        topic = step.get("topic")
        decision = step.get("decision")
        interest = step.get("interest")

        if topic:
            topic_counts[topic] += 1
            # A return: this topic was previously shelved and is now revisited.
            if shelved_open.get(topic, 0) > 0:
                returns[topic] += 1
                shelved_open[topic] = 0

        if thread_id:
            t = threads.setdefault(
                thread_id,
                {"thread_id": thread_id, "topic": topic, "steps": 0, "interests": []},
            )
            t["steps"] += 1
            if topic:
                t["topic"] = topic
            if isinstance(interest, int):
                t["interests"].append(interest)

        if isinstance(interest, int):
            interests.append(interest)

        if decision == "shelve" and topic:
            shelved_open[topic] = shelved_open.get(topic, 0) + 1

    thread_list: list[dict[str, Any]] = []
    for t in threads.values():
        ints = t.pop("interests")
        t["avg_interest"] = round(sum(ints) / len(ints), 2) if ints else None
        t["max_interest"] = max(ints) if ints else None
        thread_list.append(t)
    thread_list.sort(key=lambda t: (t["steps"], t["max_interest"] or 0), reverse=True)

    recurrence = {topic: c for topic, c in topic_counts.items() if c > 1}
    stated_avg = round(sum(interests) / len(interests), 2) if interests else None

    note = _stated_vs_revealed_note(stated_avg, thread_list, dict(returns), recurrence)

    return {
        "threads": thread_list,
        "top_threads": thread_list[:3],
        "topic_recurrence": recurrence,
        "shelve_returns": dict(returns),
        "total_shelve_returns": int(sum(returns.values())),
        "stated_avg_interest": stated_avg,
        "stated_vs_revealed_note": note,
    }


def _stated_vs_revealed_note(
    stated_avg: float | None,
    thread_list: list[dict[str, Any]],
    returns: dict[str, int],
    recurrence: dict[str, int],
) -> str | None:
    """A short, neutral note juxtaposing stated interest with revealed behaviour."""
    if not thread_list:
        return None
    parts: list[str] = []
    if stated_avg is not None:
        parts.append(f"Stated interest averages {stated_avg}.")
    longest = thread_list[0]
    parts.append(
        f"Longest thread ran {longest['steps']} step(s) on "
        f"\"{longest.get('topic') or '?'}\"."
    )
    if returns:
        returned = ", ".join(f'"{t}" ({n}x)' for t, n in returns.items())
        parts.append(f"Returned to after shelving: {returned}.")
    if recurrence:
        top = max(recurrence.items(), key=lambda kv: kv[1])
        parts.append(f'Most recurrent topic: "{top[0]}" ({top[1]} steps).')
    return " ".join(parts)
