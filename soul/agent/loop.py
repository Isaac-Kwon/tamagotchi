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
from ..storage import inbox, journal, outbox, state as state_store
from . import actions as actions_mod
from . import context as context_mod
from . import prompts, sandbox, skill_runner, skills as skills_mod, soul
from .llm import LLMError, TranscriptRecorder, run_tool_loop
from .preempt import StepController, StepTimeout

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
    to the note so the experiment's result is preserved alongside the code. The
    cwd is the persistent ``data/home/`` (not the ephemeral ``sandbox/``) so any
    files the snippet writes with relative paths survive into later steps. A
    failing snippet is data, not an error — it never fails the step.
    """
    code = _extract_code(content)
    if not code:
        return content, None
    result = sandbox.run_python(
        code,
        work_dir=paths.home_dir,
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


def _run_skill_action(
    cfg: Config, paths: DataPaths, skill_name: str, topic: str
) -> tuple[str, str, str | None]:
    """Execute a self-authored ``skill:<name>`` action out-of-process (spec P8).

    The skill is given a simple, neutral params dict — ``{"topic": <act topic>}``
    — and its returned markdown becomes this step's content. A timeout, crash, or
    malformed output is turned into a "skill failed" markdown result: the step
    still proceeds (the loop never dies) and the skill's failure counter advances,
    auto-disabling it at the configured threshold. Returns
    ``(content, skill_used, sandbox_backend)``.
    """
    result = skill_runner.run_skill(cfg, paths, skill_name, {"topic": topic})
    if result.ok:
        skills_mod.record_success(paths, skill_name)
    else:
        skills_mod.record_failure(
            paths, skill_name,
            auto_disable_after=cfg.skills.auto_disable_after_failures,
        )
    return result.output, skill_name, result.backend


def run_step(
    cfg: Config,
    paths: DataPaths,
    llm: Any,
    *,
    controller: StepController | None = None,
) -> dict[str, Any]:
    """Run one wake step. Returns the journal record that was appended.

    ``llm`` is any object exposing ``chat(messages, tools=None, json_object=...,
    recorder=...)`` — the real client or a FakeLLM.

    ``controller`` (a :class:`~soul.agent.preempt.StepController`) enforces the
    step deadline and chat preemption at every LLM-call boundary (spec P5/P7).
    When omitted the step runs with no deadline and no preemption (M1 behaviour,
    used by ``--once`` and most tests).
    """
    # 0. Keep the derived wiki index in sync with the md source (spec P3.5).
    try:
        wiki.ensure_index(paths)
    except Exception:  # noqa: BLE001 — a stale index must not block a step.
        pass

    # 1. Recall context + step id (persist the incremented counter with the step).
    step_id, st = state_store.next_step_id(paths.state_json)
    recorder = TranscriptRecorder(paths.transcript_file(step_id))

    # Progress captured so a step-timeout can preserve partial artifacts (P5).
    progress: dict[str, Any] = {"action": None, "topic": None, "content_path": None}

    def _boundary(phase: str, messages: list[dict[str, Any]] | None = None,
                  *, tool_rounds_done: int = 0, act_result: Any = None) -> None:
        if controller is not None:
            controller.boundary(
                phase, messages, tool_rounds_done=tool_rounds_done, act_result=act_result
            )

    if controller is not None:
        controller.step_id = step_id

    try:
        return _run_step_body(
            cfg, paths, llm, st, step_id, recorder, controller, progress, _boundary
        )
    except StepTimeout:
        return _record_error(
            paths, step_id, st, recorder, phase="timeout", error="step_timeout",
            action=progress["action"], topic=progress["topic"],
            content_path=progress["content_path"],
            preempted=bool(controller and controller.preempted),
        )


def _run_step_body(
    cfg: Config,
    paths: DataPaths,
    llm: Any,
    st: dict[str, Any],
    step_id: str,
    recorder: TranscriptRecorder,
    controller: StepController | None,
    progress: dict[str, Any],
    _boundary: Any,
) -> dict[str, Any]:

    # Drain the observer inbox atomically at step start (spec P4/P5).
    delivered = inbox.drain(paths)
    inbox_delivered_ids = [m.get("id") for m in delivered if m.get("id")]

    # Drain any resolved/declined outbox requests (spec P4). Unconditional even
    # when the request tool is disabled — a pending resolution still reaches the
    # agent — and attachments are copied into home/ so code experiments can read
    # them.
    resolved = outbox.drain_new_resolutions(paths, home_dir=paths.home_dir)
    observer_resolved_ids = [r.get("id") for r in resolved if r.get("id")]

    # Self-authored skills (spec P8): the enabled ones become skill:<name> actions
    # this step; a one-time notice about any auto-disabled skill is surfaced now.
    if cfg.skills.enabled:
        enabled_skills = skills_mod.list_enabled(paths)
        skill_notices = skills_mod.drain_notices(paths)
    else:
        enabled_skills = []
        skill_notices = []

    ctx = context_mod.assemble_context(
        paths,
        recent_steps_n=cfg.agent.context_recent_steps,
        serendipity_rate=cfg.agent.serendipity_rate,
        inbox_messages=delivered,
        resolved_requests=resolved,
        skill_notices=skill_notices,
    )

    # 2. ACT call — a small tool-use loop (wiki always; web too) (spec P3.5).
    act_actions = actions_mod.shuffled_actions(
        inbox_pending=bool(delivered), skills=enabled_skills
    )
    act_messages = prompts.build_act_messages(
        context_block=ctx.to_block(), actions=act_actions
    )

    wiki_ops: list[dict[str, Any]] = []
    web_visits: list[str] = []
    outbox_ops: list[dict[str, Any]] = []

    def _dispatch(name: str, arguments: Any) -> str:
        result = knowledge_tools.dispatch(
            paths, name, arguments,
            web_config=cfg.web_actions,
            observer_requests_config=cfg.observer_requests,
            step_id=step_id,
        )
        wiki_ops.extend(result.wiki_ops)
        web_visits.extend(result.web_visits)
        outbox_ops.extend(result.outbox_ops)
        return result.content

    act_tools = knowledge_tools.act_tools(
        include_web=cfg.web_actions.enabled,
        include_skills=cfg.skills.enabled,
        include_observer_requests=cfg.observer_requests.enabled,
    )

    # Boundary before ACT: enforce the deadline / yield to a live chat (P5/P7).
    _boundary("act", act_messages)

    try:
        loop_res = run_tool_loop(
            llm,
            act_messages,
            tools=act_tools,
            dispatch=_dispatch,
            recorder=recorder,
            max_rounds=cfg.knowledge.max_tool_rounds,
            on_round=lambda convo, i: _boundary("tools", convo, tool_rounds_done=i),
        )
        act_json, act_resp = _finalize_json(llm, loop_res.messages, loop_res.response, recorder)
    except LLMError as exc:
        return _record_error(paths, step_id, st, recorder, phase="act", error=str(exc),
                             llm_failure=True)

    if act_json is None:
        return _record_error(
            paths, step_id, st, recorder, phase="act", error="act_json_unparseable"
        )

    action = act_json.get("action")
    if not actions_mod.is_known_action(
        action, inbox_pending=bool(delivered), skills=enabled_skills
    ):
        # Neutral fallback rather than failing the step.
        action = "free_write"
    topic = str(act_json.get("topic") or "").strip() or "(untitled)"
    content = str(act_json.get("content") or "")
    progress["action"] = action
    progress["topic"] = topic

    # 2b. code_experiment / skill:<name>: run out-of-process via the sandbox
    # ladder (spec P3/P8). A skill's markdown output replaces the step content;
    # a failed skill yields failure text but never fails the step.
    sandbox_backend = None
    skill_used = None
    if action == "code_experiment" and cfg.sandbox.enabled:
        content, sandbox_backend = _run_code_experiment(cfg, paths, content)
    elif action.startswith(actions_mod.SKILL_PREFIX) and cfg.skills.enabled:
        skill_name = action[len(actions_mod.SKILL_PREFIX):]
        content, skill_used, sandbox_backend = _run_skill_action(
            cfg, paths, skill_name, topic
        )

    # 3. Save the ACT output to notes/.
    note_name = f"{step_id}.md"
    note_path = paths.note_file(note_name)
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(content, encoding="utf-8")
    content_rel = f"notes/{note_name}"
    progress["content_path"] = content_rel

    # 4. REFLECT call (no tools).
    reflect_messages = prompts.build_reflect_messages(
        act_action=action,
        act_topic=topic,
        act_content=content,
        previous_interest=ctx.thread.previous_interest,
    )
    # Boundary before REFLECT: enforce the deadline / yield to a live chat.
    _boundary("reflect", reflect_messages,
              act_result={"action": action, "topic": topic, "content_path": content_rel})
    try:
        reflect_json, reflect_resp = _parse_with_fallback(llm, reflect_messages, recorder)
    except LLMError as exc:
        return _record_error(
            paths, step_id, st, recorder, phase="reflect", error=str(exc),
            action=action, topic=topic, content_path=content_rel, llm_failure=True,
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
    # The previous step's *decision* carries the thread (ctx.thread is only
    # populated when it was 'deepen'), not the topic wording — the model
    # rephrases the topic line between steps, so string equality would
    # fragment nearly every deepened thread.
    if ctx.thread.thread_id:
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
        skill_used=skill_used,
        sandbox_backend=sandbox_backend,
        inbox_delivered=inbox_delivered_ids,
        observer_requests=[op["id"] for op in outbox_ops],
        observer_resolved=observer_resolved_ids,
        llm=llm_meta,
        preempted=bool(controller and controller.preempted),
    )
    if mood_raw is not None:
        record["mood_raw"] = mood_raw  # preserve out-of-enum original (spec P2)

    journal.append_step(paths, record)

    # 9. Update state.json (atomic), including revealed-interest signals.
    _update_state(st, record, thread_id, topic, interest, decision)
    _update_revealed(paths, st)
    st["open_requests"] = len(outbox.open_requests(paths))
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
        if thread.get("thread_id") not in (None, thread_id):
            thread = {"topic": topic, "steps": 0, "interest_series": []}
        thread["topic"] = topic  # label follows the latest step's wording
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
    llm_failure: bool = False,
    preempted: bool = False,
) -> dict[str, Any]:
    """Record a kind:"error" step and skip (spec P2 JSON robustness end state).

    ``llm_failure`` distinguishes an LLM outage/timeout (which the scheduler's
    circuit breaker counts, spec P5) from a parse failure or a step timeout
    (which it does NOT). It is surfaced on the error payload for the scheduler.
    """
    record = journal.new_step_record(
        step_id,
        kind="error",
        action=action,
        topic=topic,
        content_path=content_path,
        transcript_path=f"transcripts/{step_id}.jsonl",
        preempted=preempted,
        error={"phase": phase, "message": error, "llm_failure": llm_failure},
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
