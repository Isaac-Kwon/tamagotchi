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

import random
import re
from datetime import datetime, timezone
from typing import Any

from ..config import Config
from ..knowledge import tools as knowledge_tools
from ..knowledge import wiki
from ..paths import DataPaths
from ..storage import inbox, journal, state as state_store
from . import actions as actions_mod
from . import context as context_mod
from . import prompts, sandbox, soul
from .llm import LLMError, TranscriptRecorder, run_tool_loop

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


def _finalize_json(
    llm: Any,
    messages: list[dict[str, Any]],
    resp: Any,
    recorder: TranscriptRecorder,
) -> tuple[dict[str, Any] | None, Any]:
    """Apply stages 2-3 of the JSON fallback to an already-obtained response.

    Stage 1/2 (direct + outermost-braces) live in :func:`_try_parse`; if both
    fail, a single correction re-call is made (stage 3). Returns
    ``(parsed_or_None, last_response)``.
    """
    parsed = _try_parse(resp.content)
    if parsed is not None:
        return parsed, resp

    correction = messages + [
        {"role": "assistant", "content": resp.content},
        {"role": "user", "content": prompts.CORRECTION_PROMPT},
    ]
    resp2 = llm.chat(correction, json_object=True, recorder=recorder)
    return _try_parse(resp2.content), resp2


def _parse_with_fallback(
    llm: Any,
    messages: list[dict[str, Any]],
    recorder: TranscriptRecorder,
) -> tuple[dict[str, Any] | None, Any]:
    """Run a call and apply the 3-stage JSON robustness fallback (spec P2).

    Returns ``(parsed_or_None, last_response)``. Used by REFLECT (no tools).
    """
    resp = llm.chat(messages, json_object=True, recorder=recorder)
    return _finalize_json(llm, messages, resp, recorder)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_thread_id(step_counter: int) -> str:
    return f"th-{step_counter:04d}"


_CODE_FENCE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)


def _extract_code(content: str) -> str:
    """Pull python out of a code_experiment result: fenced blocks, else raw."""
    blocks = _CODE_FENCE.findall(content or "")
    if blocks:
        return "\n\n".join(b.strip() for b in blocks)
    return (content or "").strip()


def _run_code_experiment(
    cfg: Config, paths: DataPaths, content: str
) -> tuple[str, str | None]:
    """Run the snippet from a code_experiment through the sandbox ladder (P3).

    Returns ``(augmented_content, sandbox_backend)``. The run output is appended
    to the note so the experiment's result is preserved alongside the code. A
    failing snippet is data, not an error — it never fails the step.
    """
    code = _extract_code(content)
    if not code:
        return content, None
    result = sandbox.run_python(
        code,
        work_dir=paths.sandbox_dir,
        timeout_seconds=cfg.sandbox.timeout_seconds,
        backend=cfg.sandbox.backend,
    )
    note = (
        f"\n\n---\n\n**Execution** (backend: `{result.backend}`"
        f"{', not isolated' if not result.isolated else ''}"
        f"{', timed out' if result.timed_out else ''}):\n\n"
        f"```\n{(result.stdout or '').strip()}\n```"
    )
    if (result.stderr or "").strip():
        note += f"\n\nstderr:\n```\n{result.stderr.strip()}\n```"
    return content + note, result.backend


def run_step(cfg: Config, paths: DataPaths, llm: Any) -> dict[str, Any]:
    """Run one wake step. Returns the journal record that was appended.

    ``llm`` is any object exposing ``chat(messages, tools=None, json_object=...,
    recorder=...)`` — the real client or a FakeLLM.
    """
    # 0. Keep the derived wiki index in sync with the md source (spec P3.5).
    try:
        wiki.ensure_index(paths)
    except Exception:  # noqa: BLE001 — a stale index must not block a step.
        pass

    # 1. Recall context + step id (persist the incremented counter with the step).
    step_id, st = state_store.next_step_id(paths.state_json)
    recorder = TranscriptRecorder(paths.transcript_file(step_id))

    # Drain the observer inbox atomically at step start (spec P4/P5).
    delivered = inbox.drain(paths)
    inbox_delivered_ids = [m.get("id") for m in delivered if m.get("id")]

    ctx = context_mod.assemble_context(
        paths,
        recent_steps_n=cfg.agent.context_recent_steps,
        serendipity_rate=cfg.agent.serendipity_rate,
        inbox_messages=delivered,
    )

    # 2. ACT call — a small tool-use loop (wiki always; web too) (spec P3.5).
    act_actions = actions_mod.shuffled_actions(inbox_pending=bool(delivered))
    act_messages = prompts.build_act_messages(
        context_block=ctx.to_block(), actions=act_actions
    )

    wiki_ops: list[dict[str, Any]] = []
    web_visits: list[str] = []

    def _dispatch(name: str, arguments: Any) -> str:
        result = knowledge_tools.dispatch(paths, name, arguments, web_config=cfg.web_actions)
        wiki_ops.extend(result.wiki_ops)
        web_visits.extend(result.web_visits)
        return result.content

    act_tools = knowledge_tools.act_tools(include_web=cfg.web_actions.enabled)

    try:
        loop_res = run_tool_loop(
            llm,
            act_messages,
            tools=act_tools,
            dispatch=_dispatch,
            recorder=recorder,
            max_rounds=cfg.knowledge.max_tool_rounds,
        )
        act_json, act_resp = _finalize_json(llm, loop_res.messages, loop_res.response, recorder)
    except LLMError as exc:
        return _record_error(paths, step_id, st, recorder, phase="act", error=str(exc))

    if act_json is None:
        return _record_error(
            paths, step_id, st, recorder, phase="act", error="act_json_unparseable"
        )

    action = act_json.get("action")
    if not actions_mod.is_known_action(action, inbox_pending=bool(delivered)):
        # Neutral fallback rather than failing the step.
        action = "free_write"
    topic = str(act_json.get("topic") or "").strip() or "(untitled)"
    content = str(act_json.get("content") or "")

    # 2b. code_experiment: run the snippet through the sandbox ladder (spec P3).
    sandbox_backend = None
    if action == "code_experiment" and cfg.sandbox.enabled:
        content, sandbox_backend = _run_code_experiment(cfg, paths, content)

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
        serendipity_note=ctx.serendipity_note_path,
        transcript_path=f"transcripts/{step_id}.jsonl",
        wiki_ops=wiki_ops,
        web_visits=web_visits,
        sandbox_backend=sandbox_backend,
        inbox_delivered=inbox_delivered_ids,
        llm=llm_meta,
    )
    if mood_raw is not None:
        record["mood_raw"] = mood_raw  # preserve out-of-enum original (spec P2)

    journal.append_step(paths, record)

    # 9. Update state.json (atomic), including revealed-interest signals.
    _update_state(st, record, thread_id, topic, interest, decision)
    _update_revealed(paths, st)
    state_store.write_state(paths.state_json, st)

    return record


def _update_revealed(paths: DataPaths, st: dict[str, Any]) -> None:
    """Refresh the state's revealed-interest snapshot from the journal (P2)."""
    try:
        rev = journal.revealed_interest(journal.read_all(paths))
    except Exception:  # noqa: BLE001 — never let derivation crash a step.
        return
    st["revealed"] = {
        "top_threads": rev.get("top_threads", []),
        "stated_vs_revealed_note": rev.get("stated_vs_revealed_note"),
    }


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
