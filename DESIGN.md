[English](DESIGN.md) | [한국어](DESIGN.ko.md)

# DESIGN — Design Decisions and Rationale

This document covers "why it was built this way". For "what exists", see
`STRUCTURE.md`; for "how to reproduce it", see `README.md`. Each section points
to the corresponding section of `PLAN.md` (P0–P11), and wherever the actual
code diverged from the plan, that is written down plainly rather than hidden.

## 1. Blank-slate philosophy and prompt principles (PLAN §3, P2)

The core constraint: SOUL.md starts nearly empty (`soul/paths.py:SOUL_SEED` —
just the single line "This file is owned and edited only by the agent
itself."), and no tastes, personality, or interests are seeded anywhere. This
principle governs the entire prompt design (`soul/agent/prompts.py`):

- **No personality adjectives or example topics**: `ACT_SYSTEM_PROMPT`/
  `REFLECT_SYSTEM_PROMPT` describe only the situation and the mechanics ("Time
  passes in discrete steps. On each step you choose exactly one action...").
  There are no adjectives like "a curious agent", and no example topics like
  "for instance, if you like coding".
- **Shuffled action list**: `soul/agent/actions.py:shuffled_actions()` shuffles
  the order with `random.shuffle` every step. This prevents position bias (the
  tendency to pick the first item), and `prompts.render_action_list` merely
  renders the given order as-is — it never uses a hard-coded order.
- **Symmetric decision definitions**: the four decisions
  `deepen`/`shelve`/`abandon`/`new` exist in `DECISION_DEFINITIONS` only as
  one-line neutral definitions each. The structure is balanced so that none of
  them reads as "the better choice".
- **reason comes before decision**: the field order of the REFLECT response
  JSON itself is fixed as `{"interest", "interest_delta", "mood", "reason",
  "decision", "summary", "soul_update"}`, and the system prompt explicitly
  says "Write your reason BEFORE stating the decision". This is a device to
  reduce the pattern of blurting out a decision first and rationalizing it
  after the fact.
- **interest_delta as a relative anchor**: with an absolute scale alone (1–10,
  anchored only at the endpoints), LLM self-ratings tend to cluster between
  6 and 8 (central tendency), so we also ask "are you more/less/similarly
  drawn to this topic than the last time you rated it?" (`interest_delta`:
  more/less/same/first). `soul/agent/context.py:_derive_thread` finds the
  previous `interest` in the same thread and supplies it to the REFLECT
  prompt (`build_reflect_messages`) as an explicit comparison baseline.
- **soul_update defaults to false**: the prompt pins it down as "true only
  when something durable emerged", and `loop.py` actually overwrites SOUL.md
  only when `soul_update.update is True` and the content is non-empty.

## 2. Separating stated vs revealed interest (PLAN §P0/P2)

On the premise that self-reported (stated) interest can be vulnerable to the
LLM's positivity bias and confabulation, **signals revealed through behavior
are derived from the journal by a pure function, independent of the LLM**
(`soul/storage/journal.py:revealed_interest`):

- thread persistence length (how many steps continued under the same
  thread_id)
- whether the agent actually returned to a topic after shelving it, and how
  many times (returns)
- how often the same topic reappears (topic recurrence)

These values are **not stored but computed at query time** (`_update_revealed`
does fill a cache when state.json is updated, but the source of truth is
always recomputation from the journal). The gap between stated and revealed is
not hidden: it is exposed side by side in the API (`/api/revealed`), the UI
(the "words vs actions" tab), and the daily report context
(`report.py:build_report_messages`), so the agent itself gets to see the gap
between its words and its actions.

## 3. Environmental serendipity (PLAN §P2 "environmental serendipity")

The same model with the same blank-slate prompt risks converging on the
model's default persona. Treating individuality as "prior + the accidents of
the path taken", serendipity is supplied **by random draw, not by content**:

- **Shuffled action list** (see 1 above)
- **Random resurfacing of past notes**: `context.py:_pick_serendipity_note`
  draws one of `notes/*.md` uniformly with probability `serendipity_rate`
  (default 0.3) and slips it into the context as "a note you wrote before".
  Because it is drawn uniformly from the file list rather than selected by
  content, no particular topic is favored.
- **Observer inbox**: by design, serendipity that already comes from outside
  (it is unpredictable what a human will leave).

## 4. The ACT/REFLECT two-call split (PLAN §P2)

One step consists of two separate LLM calls: **① ACT** — choose and carry out
an action → `{"action","topic","content"}`, **② REFLECT** — look at the
finished output and self-rate + decide → structured JSON (no tools). Mixing
free-form narration and structured JSON in a single call makes parsing
fragile, and above all, **evaluating a finished artifact is more honest than
pre-rating an action that hasn't even happened yet** (comments in `loop.py`
and PLAN P2). REFLECT is given no tools — if the evaluation phase could call
the wiki/web tools again, the evaluation itself could be contaminated
(`knowledge/tools.py`, "REFLECT gets no tools").

## 5. Preserving chain-of-thought transcripts (PLAN §P2.5)

`soul/agent/llm.py:TranscriptRecorder` appends every LLM round trip (the full
request messages, tool_calls and results per tool round, the raw response, and
the `reasoning_content`/`reasoning` fields verbatim if present) to
`data/transcripts/<step_id>.jsonl`, one line at a time. `LLMClient` and
`FakeLLM` use the same recorder interface, so transcripts accumulate the same
way in mock mode. Why no field forcing the model to "narrate your thinking"
was added: such a field would be prompt contamination and could hurt
performance and neutrality, so the `reason` field was made responsible for
the "minimal explicit rationale" instead. There are three viewing paths:
① the "thought process" tab in the UI step detail, ② `GET
/api/step/{id}/transcript`, ③ MCP `read_transcript(step_id)`. Transcripts are
not committed to the data git, for reasons of size and noise
(`transcripts/` in `paths.py:DATA_GITIGNORE`).

## 6. Chat preemption protocol (PLAN §P7)

The agent loop (synchronous) and the API server (asynchronous) are separate
processes, so to minimize IPC, **a control file is reused as a signal bus** —
the same pattern as `state.json`.

- **Start**: on the first message of `POST /api/chat`,
  `soul/web/chat.py:ChatManager.send` atomically writes `control/chat.json`
  as `{active:true, session_id, started_at, last_message_at}`
  (`storage/control.py`, tmp+`os.replace`). The chat reply itself is produced
  by the API server **calling the LLM directly, immediately**, using SOUL.md
  + recent steps + session turns — the user does not wait for the loop.
- **Interrupting the loop**: `soul/agent/preempt.py:StepController.boundary`
  checks `control/chat.json` before the ACT call, between each tool round,
  and before the REFLECT call — that is, at **every LLM call boundary**. If
  active, it stops at that point (the call already in flight is allowed to
  finish before stopping).
- **State preservation**: at the moment of stopping, a snapshot
  `{step_id, phase, messages_so_far, tool_rounds_done, act_result,
  started_at}` is saved to `control/paused_step.json` and `state.status`
  is updated to `"chatting"`. Because the loop simply blocks inside the
  Python stack (`_check_preempt` polls with `sleep`), "resuming" is really
  just "unblock and keep executing" — the in-memory state is never destroyed.
  `paused_step.json` exists solely for **crash recovery across process
  restarts**.
- **Resuming**: the chat becomes inactive on `POST /api/chat/end` or when
  `last_message_at` exceeds `chat.idle_end_seconds` (default 180 seconds).
  The loop polls at `chat.preempt_poll_seconds` intervals (default 2 seconds)
  and then resumes. If `chat.preempt_max_wait_minutes` (default 30 minutes)
  is exceeded, the loop resumes even mid-chat and yields again at the next
  boundary (preventing infinite waiting).
- **Crash safety**: on restart, `scheduler.run_scheduler` calls
  `preempt.recover_paused_step` first. An LLM conversation that spans a
  process restart cannot be reliably reconstructed, so a leftover snapshot is
  recorded in the journal as `kind:"error"`, `preempted:true`, and the loop
  moves on to a new step.
- **Recording toggle**: with `record=false` (the default), the session exists
  only in the API server's memory and disappears on restart — the UI honestly
  labels this "not remembered". Only with `record=true` does it persist to
  `chat/recorded.jsonl`, and user messages then flow through the inbox into
  the context of the next wake.

## 7. Scheduler policy (PLAN §P5)

`soul/agent/scheduler.py:run_scheduler` repeats
`check_preempt() → check_report() → run_step() → wait()`.

- **Heartbeat vs continuous**: `compute_wait()` computes the start time of
  the next step. Heartbeat mode uses
  `max(previous step start + heartbeat, previous step end + min_step_gap)` —
  that is, **even if a step runs longer than the period, it is neither
  skipped nor killed**; only the minimum separation gap
  (`min_step_gap_seconds`, default 60 seconds) is guaranteed. Continuous mode
  applies only `previous step end + min_step_gap`, chaining the next step as
  soon as one finishes. Both modes share the same `min_step_gap_seconds`
  parameter.
- **The step timeout is a separate safety net**: independent of the "lenient"
  heartbeat/continuous policy, `StepController` checks a hard deadline of
  `step_timeout_minutes` (default 45 minutes) at every LLM call boundary
  inside a step (`_check_deadline`; each individual LLM call also has its own
  120-second timeout, so a deadline overrun cannot slip by more than one
  call's length). On overrun it raises `StepTimeout`, and `loop.run_step`
  records the step as `kind:"error"`, `error:"step_timeout"` while preserving
  the partial outputs and transcript accumulated so far, then moves on to the
  next step. This is the last line of defense against runaways (infinite tool
  loops, etc.), and since it means "the work just took long" rather than an
  LLM outage, it is not counted toward the circuit breaker
  (`scheduler.is_llm_failure` distinguishes via the `error.llm_failure`
  flag).
- **Circuit breaker**: `CircuitBreaker` counts only **consecutive LLM
  failures** (error steps with `llm_failure: true`). After
  `consecutive_error_backoff` (default 5) consecutive failures, the next wait
  time is multiplied by 4 (`CIRCUIT_MULTIPLIER`); on success it resets
  immediately. Parse failures and step timeouts are not "API outages" and are
  excluded from the count.
- The report-time check (`report.is_due`) happens between steps in both
  modes, and is based on `zoneinfo` (e.g. `Asia/Seoul`). `next_wake_at` in
  `state.json` always reflects the actual next start time computed by
  `compute_wait()`, so the UI countdown stays accurate.
- **Stale detection diverged from PLAN ("stale when updated_at exceeds twice
  the base interval").** `state.json` is written **only when a step ends**,
  and under the long-step policy above a step can far exceed the period, so
  the original rule almost always misjudged a normally progressing step as
  stale in continuous mode (base 60 seconds). The current rule
  (`soul/web/api.py:stale_deadline`): stale only if there has been no write
  by `max(updated_at + base interval, next_wake_at) + step_timeout_minutes` —
  that is, the loop is judged dead only past "the time by which a live loop
  must have written something, given the hard deadline". The same reference
  time is sent down to `/api/state` as `stale_at`, so even after SSE goes
  quiet the client can flip to stale using its own clock (a dead loop cannot
  produce the very event that would carry stale=true).

## 8. The sandbox ladder (PLAN §P3)

`soul/agent/sandbox.py:select_backend` tries the best isolation first, in
order:

1. **Linux native** — `bwrap` (`--unshare-all --die-with-parent`; if absent,
   `unshare --user --net --pid --map-root-user`). No daemon required, minimal
   overhead.
2. **Docker** — only when `docker info` succeeds. `--network none`,
   `--memory 256m`, `--pids-limit 128` — **the only strong isolation on
   Windows**.
3. **plain subprocess** — the last fallback. It pins cwd to `data/sandbox`
   and minimizes environment variables, but it is **not isolation**.

Honesty is the heart of this design: `SandboxResult.isolated` must be `False`
for the subprocess fallback, and this value lands verbatim in the journal's
`sandbox_backend` field and the startup log. Which backend was selected is
never hidden. This ladder is shared and reused by both the `code_experiment`
action and self-authored skill execution (P8).

## 9. Self-authored skill lifecycle (PLAN §P8)

Built-in skills (`actions.py`/`webtools.py`) belong to the source repository,
so the agent structurally cannot change them (it can only write to the data
directory). Self-authored skills:

- **Registration**: when `skill_write(name, description, code)` is called in
  the ACT tool loop, `soul/agent/skills.py:create_skill` validates the name
  as a slug, **statically rejects imports outside the standard library** via
  `soul/agent/skills.py:check_imports` (AST parsing), verifies the existence
  of a `run(params: dict) -> dict` function, then writes `manifest.json` +
  `skill.py` and commits to the data git. On success, `skill:<name>` appears
  neutrally in the action list from the next step onward.
- **Execution**: `skill_runner.py` runs the skill code **without importing it
  into the agent process**, as a separate subprocess through the sandbox
  ladder of section 8 above. params go in as stdin JSON, the result comes
  back as stdout JSON (`{"output": "<markdown>"}`). The import check is run
  again right before execution, so it stays safe even if the file changed on
  disk after registration.
- **Failure isolation**: timeouts (`skills.timeout_seconds`, default 20
  seconds), exceptions, and non-JSON output are all converted into a "skill
  failed" markdown result, so **the step proceeds normally and the loop never
  dies** (`skill_runner.run_skill` does not raise). Each failure increments
  `manifest.failures`, and on reaching `skills.auto_disable_after_failures`
  (default 3) the skill is automatically set to `enabled:false` and
  committed. A one-time notice that "this skill was disabled" is delivered
  into the next context via `skills.drain_notices`, leaving it up to the
  agent whether to fix it or abandon it.

## 10. Storage choice rationale (PLAN §P0/P1)

JSONL (journal) + Markdown (notes/wiki/reports) + `state.json` (a single
snapshot) serve as primary storage; SQLite is used **only as a derived index
for wiki search (`index/wiki.sqlite3`)**. Rationale: PLAN's requirement that
"one directory be importable wholesale into another AI for diagnosis" (P1) —
text files are readable as-is by both humans and AIs. The data volume is
small to begin with (a few KB per step). The SQLite index is **always fully
rebuildable from the md originals** (`wiki.rebuild_index`), and on startup an
mtime mismatch triggers an automatic rebuild (`wiki.ensure_index`), so the
index itself is not committed to the data git (it is a derivative, not an
original). sqlite3 + FTS5 are in the standard library, so there is no added
dependency.

The reason **the data directory is itself a separate git repository**
(`soul/paths.py:init_data_dir`) also flows from the same diagnosability
requirement — only by being fully separated from the source repository can
`data/` be handed wholesale into another AI's context, and SOUL.md's git
history itself becomes a diff timeline, "the growth history of the soul"
(P1/§3). What gets committed: SOUL.md, notes/, wiki/, skills/, reports/
(plus the journal committed alongside once a day when the report is
generated); `state.json`/`index/`/`control/`/`logs/`/`sandbox/`/
`transcripts/`/`agent.lock` are explicitly excluded via `data/.gitignore`
(`DATA_GITIGNORE`) — because they are derivatives, volatile, or machine-local.

## 11. Process separation and the "single writer" principle (PLAN §P5)

The agent loop (`run_agent.py`, synchronous) and the API server
(`run_web.py`, uvicorn asynchronous) are **two separate processes**, sharing
only the `data/` directory. The rationale is fault isolation (the UI stays
alive even if the loop dies), and the simplicity of not forcing a synchronous
loop and asynchronous web concurrency into one process.

**The writer is fixed to exactly one**: substantive writes to the data
directory are done only by the agent loop process (SOUL.md, journal, wiki,
skills, reports, state.json). The API server is read-only in principle, with
exactly three exceptions — appending to the inbox `pending.jsonl`
(`storage/inbox.append_pending`), appending recording-consented conversations
to `chat/recorded.jsonl` (`web/chatlog.py`), and the preemption signal
`control/chat.json` (`storage/control.py`). The MCP server (`run_mcp.py`)
writes not even these three — it is **strictly read-only**, and opens the
wiki index only via a `mode=ro` SQLite connection. The inbox avoids
contention with a protocol of "the web only appends; the agent atomically
moves pending→delivered at step start" (`storage/inbox.py`,
`O_CREAT|O_EXCL` advisory lock). Git commit contention is resolved by the
same principle — since only one process writes to the data git, the
multi-writer problem never arises in the first place (on commit failure,
retry once; if it still fails, the files remain updated and are included in
the next commit).

## 12. The honest-framing principle (PLAN §3/P11)

A rule that runs through this entire project: **do not overclaim.**
Concretely:

- The pinned banner at the top of the UI: "This being simulates
  self-directed interest" (`soul/web/static/index.html`).
- `record=false` conversations are explicitly labeled "not remembered" in
  the UI (section 6).
- When the sandbox is not isolated (plain subprocess), `isolated:false` is
  left as-is in the journal and logs (sections 8, 9).
- The gap between stated and revealed interest is not hidden but exposed
  side by side in the UI/API/reports (section 2).
- Instead of maintaining a domain blocklist for web search, its limitations
  (the possibility of ad contamination, etc.) are honestly written down in
  the README.

## Appendix: where the plan and the actual implementation diverged

- **Frontend art source**: PLAN §P0 named "a CC0 pixel asset pack (Kenney.nl
  etc.)" as the choice, but the actual M7 implementation has
  `soul/web/static/js/room_scene.js` **generate all textures procedurally at
  boot** via Phaser's `Graphics.generateTexture()`.
  `soul/web/static/assets/` is an intentionally empty directory, and the
  `README.md` inside it explains "if richer art is needed, drop a CC0 pack
  here and swap out `preload()` in `room_scene.js`" — that is, CC0 asset
  pack integration was mentioned in the plan but not implemented, replaced
  instead by zero-dependency procedural generation.
- **Runtime dependency count**: PLAN §P0 said "four: `fastapi`, `uvicorn`,
  `httpx`, `mcp`", but the actual `requirements.txt` has one more, `tzdata`.
  It was added to keep `Asia/Seoul` report scheduling (P5) from breaking on
  Windows, whose `zoneinfo` does not bundle the IANA timezone DB — less a
  contradiction of the plan than a practical supplement that surfaced after
  it.
