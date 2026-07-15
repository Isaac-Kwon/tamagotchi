"""Wake-step orchestration — one step of the agent's life (spec P2).

Pipeline (spec P2):

    context (recall)
      -> [ACT call]  choose+carry out one action -> ACT JSON {action, topic, content}
      -> save content to data/notes/<step>.md
      -> [REFLECT call]  self-assessment JSON (no tools)
      -> append journal line
      -> update state.json
      -> if soul_update.update: rewrite SOUL.md + git commit in the data repo

JSON robustness (spec P2), applied to both ACT and REFLECT:
    1. response_format json_object,
    2. regex extraction of the outermost {...},
    3. one correction re-call,
    then record a kind:"error" step and skip.

The tool-use loop for ACT arrives in M3; here ACT is a single plain call.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from ..config import Config
from ..paths import DataPaths
from ..storage import journal, state as state_store
from . import actions as actions_mod
from . import context as context_mod
from . import prompts, soul
from .llm import LLMError, TranscriptRecorder

# Matches the outermost {...} spanning newlines (greedy) for stage-2 extraction.
_OUTER_BRACES = re.compile(r"\{.*\}", re.DOTALL)


def _try_parse(content: str) -> dict[str, Any] | None:
    """Stage 1 (direct JSON) then stage 2 (outermost-braces regex)."""
    content = (content or "").strip()
    if not content:
        return None
    # Stage 1: direct parse.
    try:
        obj = _loads_object(content)
        if obj is not None:
            return obj
    except ValueError:
        pass
    # Stage 2: extract the outermost {...} and parse that.
    match = _OUTER_BRACES.search(content)
    if match:
        try:
            return _loads_object(match.group(0))
        except ValueError:
            return None
    return None


def _loads_object(text: str) -> dict[str, Any] | None:
    import json

    obj = json.loads(text)
    return obj if isinstance(obj, dict) else None


def _parse_with_fallback(
    llm: Any,
    messages: list[dict[str, Any]],
    recorder: TranscriptRecorder,
) -> tuple[dict[str, Any] | None, Any]:
    """Run a call and apply the 3-stage JSON robustness fallback (spec P2).

    Returns ``(parsed_or_None, last_response)``.
    """
    resp = llm.chat(messages, json_object=True, recorder=recorder)
    parsed = _try_parse(resp.content)
    if parsed is not None:
        return parsed, resp

    # Stage 3: a single correction re-call.
    correction = messages + [
        {"role": "assistant", "content": resp.content},
        {"role": "user", "content": prompts.CORRECTION_PROMPT},
    ]
    resp2 = llm.chat(correction, json_object=True, recorder=recorder)
    parsed = _try_parse(resp2.content)
    return parsed, resp2


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_thread_id(step_counter: int) -> str:
    return f"th-{step_counter:04d}"


def run_step(cfg: Config, paths: DataPaths, llm: Any) -> dict[str, Any]:
    """Run one wake step. Returns the journal record that was appended.

    ``llm`` is any object exposing ``chat(messages, tools=None, json_object=...,
    recorder=...)`` — the real client or a FakeLLM.
    """
    # 1. Recall context + step id (persist the incremented counter with the step).
    step_id, st = state_store.next_step_id(paths.state_json)
    recorder = TranscriptRecorder(paths.transcript_file(step_id))
    ctx = context_mod.assemble_context(paths, recent_steps_n=cfg.agent.context_recent_steps)

    # 2. ACT call.
    act_actions = actions_mod.shuffled_actions()
    act_messages = prompts.build_act_messages(
        context_block=ctx.to_block(), actions=act_actions
    )

    try:
        act_json, act_resp = _parse_with_fallback(llm, act_messages, recorder)
    except LLMError as exc:
        return _record_error(paths, step_id, st, recorder, phase="act", error=str(exc))

    if act_json is None:
        return _record_error(
            paths, step_id, st, recorder, phase="act", error="act_json_unparseable"
        )

    action = act_json.get("action")
    if not actions_mod.is_known_action(action):
        # Neutral fallback rather than failing the step.
        action = "free_write"
    topic = str(act_json.get("topic") or "").strip() or "(untitled)"
    content = str(act_json.get("content") or "")

    # 3. Save the ACT output to notes/.
    note_name = f"{step_id}.md"
    note_path = paths.note_file(note_name)
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(content, encoding="utf-8")
    content_rel = f"notes/{note_name}"

    # 4. REFLECT call (no tools).
    reflect_messages = prompts.build_reflect_messages(
        act_action=action,
        act_topic=topic,
        act_content=content,
        previous_interest=ctx.thread.previous_interest,
    )
    try:
        reflect_json, reflect_resp = _parse_with_fallback(llm, reflect_messages, recorder)
    except LLMError as exc:
        return _record_error(
            paths, step_id, st, recorder, phase="reflect", error=str(exc),
            action=action, topic=topic, content_path=content_rel,
        )

    if reflect_json is None:
        return _record_error(
            paths, step_id, st, recorder, phase="reflect",
            error="reflect_json_unparseable",
            action=action, topic=topic, content_path=content_rel,
        )

    # 5. Normalize the self-assessment (clamp interest, normalize enums).
    interest = prompts.clamp_interest(reflect_json.get("interest"))
    interest_delta = prompts.normalize_interest_delta(reflect_json.get("interest_delta"))
    mood, mood_raw = prompts.normalize_mood(reflect_json.get("mood"))
    decision = prompts.normalize_decision(reflect_json.get("decision"))
    reason = str(reflect_json.get("reason") or "")
    summary = str(reflect_json.get("summary") or "").strip() or topic

    # 6. Thread bookkeeping (spec P4): deepen keeps thread; else fresh next step.
    if ctx.thread.thread_id and ctx.thread.topic == topic:
        thread_id = ctx.thread.thread_id
    else:
        thread_id = _new_thread_id(st["step_counter"])

    # 7. Soul update (durable-only). Rewrite + commit when requested.
    soul_update = reflect_json.get("soul_update") or {}
    soul_updated = False
    soul_commit = None
    if isinstance(soul_update, dict) and soul_update.get("update") is True:
        new_soul = str(soul_update.get("content") or "").strip()
        if new_soul:
            try:
                soul_commit = soul.write_soul(
                    paths,
                    new_soul + "\n",
                    soul_max_chars=cfg.agent.soul_max_chars,
                    commit_message=f"SOUL update @ {step_id}",
                )
                soul_updated = soul_commit is not None
            except soul.SoulWriteError:
                soul_updated = False

    # 8. Build + append the journal record.
    llm_meta = {
        "model": getattr(reflect_resp, "model", None),
        "tokens_in": getattr(act_resp, "tokens_in", 0) + getattr(reflect_resp, "tokens_in", 0),
        "tokens_out": getattr(act_resp, "tokens_out", 0) + getattr(reflect_resp, "tokens_out", 0),
        "latency_ms": getattr(act_resp, "latency_ms", 0) + getattr(reflect_resp, "latency_ms", 0),
    }
    record = journal.new_step_record(
        step_id,
        kind="wake_step",
        action=action,
        topic=topic,
        thread_id=thread_id,
        content_path=content_rel,
        interest=interest,
        interest_delta=interest_delta,
        mood=mood,
        reason=reason,
        decision=decision,
        summary=summary,
        soul_updated=soul_updated,
        soul_commit=soul_commit,
        transcript_path=f"transcripts/{step_id}.jsonl",
        llm=llm_meta,
    )
    if mood_raw is not None:
        record["mood_raw"] = mood_raw  # preserve out-of-enum original (spec P2)

    journal.append_step(paths, record)

    # 9. Update state.json (atomic).
    _update_state(st, record, thread_id, topic, interest, decision)
    state_store.write_state(paths.state_json, st)

    return record


def _update_state(
    st: dict[str, Any],
    record: dict[str, Any],
    thread_id: str,
    topic: str,
    interest: int,
    decision: str,
) -> None:
    st["status"] = "awake"
    st["last_step"] = {
        "id": record["id"],
        "action": record["action"],
        "topic": topic,
        "summary": record["summary"],
        "mood": record["mood"],
        "interest": interest,
        "decision": decision,
        "ts": record["ts"],
    }
    if decision == "deepen":
        thread = st.get("current_thread") or {"topic": topic, "steps": 0, "interest_series": []}
        if thread.get("topic") != topic:
            thread = {"topic": topic, "steps": 0, "interest_series": []}
        thread["topic"] = topic
        thread["steps"] = int(thread.get("steps", 0)) + 1
        thread.setdefault("interest_series", []).append(interest)
        thread["thread_id"] = thread_id
        st["current_thread"] = thread
    elif decision == "shelve":
        shelved = st.setdefault("shelved_threads", [])
        shelved.append({"thread_id": thread_id, "topic": topic})
        st["current_thread"] = None
    else:  # abandon / new
        st["current_thread"] = None


def _record_error(
    paths: DataPaths,
    step_id: str,
    st: dict[str, Any],
    recorder: TranscriptRecorder,
    *,
    phase: str,
    error: str,
    action: str | None = None,
    topic: str | None = None,
    content_path: str | None = None,
) -> dict[str, Any]:
    """Record a kind:"error" step and skip (spec P2 JSON robustness end state)."""
    record = journal.new_step_record(
        step_id,
        kind="error",
        action=action,
        topic=topic,
        content_path=content_path,
        transcript_path=f"transcripts/{step_id}.jsonl",
        error={"phase": phase, "message": error},
    )
    journal.append_step(paths, record)

    st["status"] = "error"
    st["last_step"] = {
        "id": step_id,
        "kind": "error",
        "error": error,
        "ts": record["ts"],
    }
    state_store.write_state(paths.state_json, st)
    return record
