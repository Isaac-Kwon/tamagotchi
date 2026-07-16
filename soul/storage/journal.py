"""Journal — append-only JSONL of step records, hourly rotation in 50-record chunks.

Each step is one JSON line in ``journal/steps-YYYY-MM-DD-HH-NN.jsonl``, where the
UTC hour rotates the file and ``NN`` is a zero-padded chunk index (starting at
``00``) that rolls once a chunk reaches :data:`MAX_CHUNK_LINES` records. This is
a deliberate divergence from spec P4's monthly rotation (``steps-YYYY-MM.jsonl``)
— smaller hour/chunk files keep the append-only log crash-safe and easy to diff.
Old monthly files are still read (see :func:`_iter_journal_files`); they are
never migrated or rewritten (append-only; ``data/`` is its own git repo).

The full step record schema (spec P4) is produced by :func:`new_step_record`;
fields not yet implemented in this milestone are present with ``null`` values so
downstream consumers can rely on a stable shape.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..paths import DataPaths

# Max records per journal chunk before rolling to the next NN (divergence from
# spec P4's monthly rotation — see module docstring).
MAX_CHUNK_LINES = 50


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


def _count_nonempty_lines(path: Path) -> int:
    """Number of non-blank lines already in a chunk file (0 if missing)."""
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as fh:
        return sum(1 for line in fh if line.strip())


def _current_chunk_file(paths: DataPaths, when: datetime) -> Path:
    """Pick the hour's chunk file to append to, rolling when it is full.

    Lists existing ``steps-YYYY-MM-DD-HH-*.jsonl`` chunks for ``when``'s UTC hour,
    takes the highest ``NN``, and rolls to ``NN+1`` once that chunk holds
    :data:`MAX_CHUNK_LINES` records. No state is cached — the count is recomputed
    on every append (single-writer per CLAUDE.md, so no locking is needed).
    """
    prefix = paths.journal_hour_prefix(when)
    existing = sorted(paths.journal_dir.glob(f"{prefix}-*.jsonl"))
    if existing:
        latest = existing[-1]
        # Derive NN from the highest-sorted chunk (fixed-width, so lexicographic
        # order matches numeric order).
        nn = int(latest.stem.rsplit("-", 1)[1])
        if _count_nonempty_lines(latest) >= MAX_CHUNK_LINES:
            nn += 1
    else:
        nn = 0
    return paths.journal_dir / f"{prefix}-{nn:02d}.jsonl"


def append_step(paths: DataPaths, record: dict[str, Any]) -> Path:
    """Append one step record as a JSON line to the current hourly journal chunk."""
    when = datetime.now(timezone.utc)
    paths.journal_dir.mkdir(parents=True, exist_ok=True)
    path = _current_chunk_file(paths, when)
    line = json.dumps(record, ensure_ascii=False)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return path


def _journal_sort_key(path: Path) -> tuple[int, int, int, int, int, str]:
    """Chronological sort key spanning both filename schemes.

    A plain lexicographic sort does *not* order the two schemes correctly:
    ``'-'`` (0x2D) < ``'.'`` (0x2E), so ``steps-2026-07-16-09-00.jsonl`` would
    sort *before* the same month's ``steps-2026-07.jsonl`` — reversing the true
    order (the monthly backlog predates the hourly chunks it was migrated to). We
    parse the numeric components instead and pad them to a fixed
    ``(year, month, day, hour, chunk)`` tuple: legacy monthly files
    (``steps-YYYY-MM``) get sentinel day/hour/chunk of ``-1`` so they read ahead
    of that month's hourly chunks (``steps-YYYY-MM-DD-HH-NN``). Unparseable names
    sort last, by name.
    """
    nums = path.stem.split("-")[1:]  # drop the "steps" prefix
    try:
        ints = [int(x) for x in nums]
    except ValueError:
        ints = []
    if 2 <= len(ints) <= 5:
        # Pad the numeric components with -1 so shorter (coarser) schemes sort
        # ahead of the finer chunks nested within them: monthly (year, month)
        # reads before that month's hourly (year, month, day, hour, chunk).
        year, month, day, hour, chunk = (ints + [-1, -1, -1, -1, -1])[:5]
    else:  # unknown scheme — sort last, deterministically by name
        year, month, day, hour, chunk = 10**9, 99, 99, 99, 99
    return (year, month, day, hour, chunk, path.name)


def _iter_journal_files(paths: DataPaths) -> list[Path]:
    """All journal files (hourly chunks + legacy monthly), chronologically ordered."""
    if not paths.journal_dir.exists():
        return []
    return sorted(paths.journal_dir.glob("steps-*.jsonl"), key=_journal_sort_key)


def read_all(paths: DataPaths) -> list[dict[str, Any]]:
    """Read every step record across all journal files, in chronological order."""
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
    """Return the last ``n`` step records across journal files (chronological)."""
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


def stats(
    steps: list[dict[str, Any]],
    *,
    timeline_limit: int = 250,
    recent_errors: int = 20,
) -> dict[str, Any]:
    """Aggregate journal steps into UI-ready statistics (pure function).

    Like :func:`revealed_interest`, this derives everything on read and stores
    nothing. It powers the web UI's stats panel:

        * distributions   — decisions / actions / moods / interest histogram,
        * timeline        — last ``timeline_limit`` wake steps, compact fields
                            only (id, ts, interest, mood, decision, action),
        * threads         — chronological thread segments (topic river),
        * errors          — count + the most recent error records.

    ``steps`` is a chronological list of step records (:func:`read_all`).
    """
    decisions: Counter[str] = Counter()
    actions: Counter[str] = Counter()
    moods: Counter[str] = Counter()
    interest_hist: Counter[int] = Counter()
    timeline: list[dict[str, Any]] = []
    thread_segments: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for step in steps:
        if step.get("kind") == "error" or step.get("error"):
            err = step.get("error") or {}
            errors.append({
                "id": step.get("id"),
                "ts": step.get("ts"),
                "phase": err.get("phase") if isinstance(err, dict) else None,
                "message": err.get("message") if isinstance(err, dict) else str(err),
            })
        if step.get("kind") != "wake_step":
            continue

        if step.get("decision"):
            decisions[step["decision"]] += 1
        if step.get("action"):
            actions[step["action"]] += 1
        if step.get("mood"):
            moods[step["mood"]] += 1
        interest = step.get("interest")
        if isinstance(interest, int):
            interest_hist[interest] += 1

        timeline.append({
            "id": step.get("id"),
            "ts": step.get("ts"),
            "interest": interest if isinstance(interest, int) else None,
            "mood": step.get("mood"),
            "decision": step.get("decision"),
            "action": step.get("action"),
        })

        # Thread segments: consecutive wake steps sharing a thread_id (threads
        # are contiguous by construction — a break in decision ends them).
        thread_id = step.get("thread_id")
        seg = thread_segments[-1] if thread_segments else None
        if seg is None or seg["thread_id"] != thread_id:
            seg = {
                "thread_id": thread_id,
                "topic": step.get("topic"),
                "steps": 0,
                "start_ts": step.get("ts"),
                "end_ts": step.get("ts"),
                "interests": [],
            }
            thread_segments.append(seg)
        seg["steps"] += 1
        seg["end_ts"] = step.get("ts")
        if step.get("topic"):
            seg["topic"] = step.get("topic")  # label follows the latest wording
        if isinstance(interest, int):
            seg["interests"].append(interest)

    for seg in thread_segments:
        ints = seg.pop("interests")
        seg["avg_interest"] = round(sum(ints) / len(ints), 2) if ints else None

    total = sum(decisions.values())
    return {
        "total_steps": len(timeline),
        "decisions": dict(decisions),
        "decision_total": total,
        "actions": dict(actions),
        "moods": dict(moods),
        "interest_hist": {str(k): v for k, v in sorted(interest_hist.items())},
        "timeline": timeline[-timeline_limit:],
        "threads": thread_segments,
        "errors": {"count": len(errors), "recent": errors[-recent_errors:]},
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
