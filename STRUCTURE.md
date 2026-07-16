[English](STRUCTURE.md) | [한국어](STRUCTURE.ko.md)

# STRUCTURE — Directory & Module Map

This is the canonical reference for "what exists". For "why it was built this
way", see `DESIGN.md`; for "how to set up/run it", see `README.md`. The tables
and fields were written from reading the actual code; wherever it differs from
`PLAN.md`, the code is what's documented here.

## Source tree (`soul/`)

### Entry points (repo root)

| File | Role |
|---|---|
| `run_agent.py` | Agent loop entry point. Defaults to the long-running scheduler; `--once` runs a single step, `--mock` uses FakeLLM. Holds `agent.lock` for the lifetime of the process. |
| `run_web.py` | API server entry point (uvicorn). With `--mock`, chat responses also use FakeLLM. |
| `run_mcp.py` | Read-only knowledge MCP server entry point (stdio). `--data-dir`, `--allow-index-rebuild` (opt-in, rebuilds derived indexes only). |
| `config.example.json` | Committed config template. `config.json` is `.gitignore`'d. |
| `requirements.txt` | `httpx`, `fastapi`, `uvicorn`, `mcp`, `tzdata` (supplements `zoneinfo` on Windows). |
| `scripts/start_agent.ps1` / `start_web.ps1` | PowerShell wrappers with exponential-backoff auto-restart on crash (assume the Windows-native venv). |

### `soul/config.py`, `soul/paths.py`

| Module | Role | Key functions/classes |
|---|---|---|
| `config.py` | Loads + validates `config.json` (dataclasses). Applies the API key resolution order. | `load_config`, `config_from_dict`, `resolve_api_key`, `Config` and its 9 section dataclasses |
| `paths.py` | Data directory path helpers + first-time initialization (tree creation, SOUL.md seed, git init). | `DataPaths`, `init_data_dir`, `DATA_SUBDIRS`, `DATA_GITIGNORE`, `SOUL_SEED` |

### `soul/agent/` — agent core

| Module | Role | Key functions/classes |
|---|---|---|
| `loop.py` | Wake-step orchestration (the heart): recall → ACT (tool loop) → save → REFLECT → journal/state update → commit on soul_update. Three-stage JSON fallback. | `run_step`, `_run_step_body`, `_parse_with_fallback`, `_record_error` |
| `scheduler.py` | Long-running loop for heartbeat/continuous modes + circuit breaker + `next_wake_at` computation + periodic autosave. | `run_scheduler`, `compute_wait`, `CircuitBreaker`, `is_llm_failure` |
| `autosave.py` | Periodic data-repo commit of accumulating history (journal/notes/home/inbox/outbox/chat) every `agent.autosave_every_steps` steps — the safety net between daily reports. | `maybe_autosave`, `is_due`, `AUTOSAVE_PATHS` |
| `preempt.py` | Chat preemption: checks `control/chat.json` at every LLM call boundary, enforces the step timeout deadline, saves/restores snapshots, recovers from crashes. | `StepController`, `StepTimeout`, `recover_paused_step` |
| `llm.py` | OpenAI-compatible chat-completions client (retry/backoff/timeout) + transcript recording + tool-use loop. | `LLMClient`, `LLMResponse`, `TranscriptRecorder`, `run_tool_loop` |
| `fake_llm.py` | `LLMClient` stand-in for tests/`--mock`. Returns queued responses in order (dict/str/`LLMResponse`/exception). | `FakeLLM` |
| `prompts.py` | English prompt templates (the core of the blank-slate philosophy). ACT/REFLECT message assembly, JSON field normalization. | `ACT_SYSTEM_PROMPT`, `REFLECT_SYSTEM_PROMPT`, `build_act_messages`, `build_reflect_messages`, `clamp_interest`, `normalize_mood`, `normalize_decision`, `normalize_interest_delta` |
| `actions.py` | Built-in action definitions (neutral verbs) + shuffling + `skill:<name>` synthesis. | `BUILTIN_ACTIONS`, `available_actions`, `shuffled_actions`, `is_known_action` |
| `webtools.py` | `web_search` (DuckDuckGo HTML parsing), `web_read` (body extraction, size/time caps), `arxiv_search` (Atom API). | `web_search`, `web_read`, `arxiv_search` |
| `skills.py` | Self-authored skill registration/lifecycle: static validation of name/code (standard library only), manifest management, failure counting/auto-disable, data git commits. | `create_skill`, `check_imports`, `has_run`, `record_success`, `record_failure`, `drain_notices` |
| `skill_runner.py` | Runner that executes skills in a separate subprocess (via the sandbox ladder). Skill code is never imported. | `run_skill`, `SkillRunResult` |
| `sandbox.py` | Isolation backend ladder: bwrap → unshare → Docker → plain subprocess. Shared by `code_experiment` and skill execution. | `select_backend`, `run_python`, `backend_is_isolated`, `describe_backend` |
| `context.py` | Recall context assembly: SOUL.md + last N steps + current thread + serendipity note + inbox + resolved observer requests + skill notices. | `assemble_context`, `RecallContext`, `ThreadInfo`, `_pick_serendipity_note` |
| `soul.py` | Reads/writes SOUL.md + data git commits. **The only module that writes SOUL.md.** | `read_soul`, `write_soul`, `SoulWriteError` |
| `report.py` | Generates a first-person retrospective in Korean (configurable) daily at a set time/timezone. Idempotent (judged by whether the date file exists). | `generate_report`, `check_report`, `is_due`, `build_report_messages` |
| `lock.py` | `agent.lock` — pid+timestamp lock, steals stale locks from dead processes (POSIX `os.kill`/Windows `OpenProcess`). | `AgentLock`, `LockError` |

### `soul/storage/` — state & history storage

| Module | Role | Key functions/classes |
|---|---|---|
| `journal.py` | Step-record JSONL append/tail (monthly rotation) + the pure derived functions `revealed_interest` and `stats`. | `new_step_record`, `append_step`, `read_all`, `tail`, `revealed_interest`, `stats` |
| `state.py` | Atomic read/write of `state.json` (tmp + `os.replace`) + step id counter. | `read_state`, `write_state`, `next_step_id`, `default_state` |
| `inbox.py` | Observer-message pending→delivered queue. The web only appends; the agent drains atomically at step start. | `append_pending`, `drain`, `has_pending`, `peek_pending` |
| `outbox.py` | Agent→observer request channel. The agent appends requests (`observer_request` tool); the web appends resolutions; status is derived by joining the two append-only logs; the agent drains new resolutions at step start via a cursor (`seen.json`) and copies attachments into `home/`. | `append_request`, `list_requests`, `open_requests`, `append_resolution`, `drain_new_resolutions`, `OutboxStateError` |
| `locks.py` | The `O_CREAT\|O_EXCL` advisory file lock shared by the inbox and outbox (5s timeout, 30s stale-steal). | `AdvisoryFileLock` |
| `control.py` | Inter-process signal files: `control/chat.json` (preemption bus), `control/paused_step.json` (snapshot). | `read_chat`, `set_chat_active`, `set_chat_inactive`, `chat_is_active`, `write_paused_step`, `read_paused_step`, `clear_paused_step` |

### `soul/knowledge/` — knowledge wiki + MCP

| Module | Role | Key functions/classes |
|---|---|---|
| `wiki.py` | Wiki source (md) CRUD + `[[link]]` parsing + SQLite FTS5 index (derived, always rebuildable) + git commits. | `write_page`, `read_page`, `search`, `graph`, `backlinks`, `rebuild_index`, `ensure_index` |
| `tools.py` | Function-calling schemas for the ACT tool loop + dispatcher (unifies wiki/web/skill/observer-request tools). | `act_tools`, `dispatch`, `WIKI_TOOLS`, `WEB_TOOLS`, `SKILL_TOOLS`, `OUTBOX_TOOLS` |
| `mcp_server.py` | Read-only MCP server (`mcp` SDK, stdio). SQLite is also connected only with `mode=ro`. | `build_server`, `serve_stdio`, `wiki_search`, `wiki_read`, `wiki_list`, `read_soul`, `query_journal`, `read_report`, `read_transcript` |

### `soul/web/` — API server + static client

| Module | Role | Key functions/classes |
|---|---|---|
| `server.py` | FastAPI app factory + static file mounting. No UI logic mixed in here (routes live entirely in `api.py`). | `create_app` |
| `api.py` | All REST + SSE routes (table below). Read-only toward the data directory as a rule. | `build_router`, `state_snapshot` |
| `events.py` | Watches `state.json` mtime and pushes state over SSE. | `state_event_stream` |
| `chat.py` | Chat sessions (in-memory) + direct LLM calls + preemption signal emission + recording toggle. One of the API server's four allowed writes. | `ChatManager`, `ChatSession`, `build_chat_messages` |
| `chatlog.py` | Appends only `record=true` conversations to `chat/recorded.jsonl`. | `append_turn`, `read_all` |
| `gitview.py` | Exposes SOUL.md's git log/per-commit diffs read-only ("the soul's growth history"). | `soul_history`, `soul_diff`, `soul_updated_at` |
| `static/` | Phaser 3 (CDN) based web client. Just one client of the API (other clients such as mobile apps can use the same API). | `index.html`, `js/{main,api,room_scene,mapping,panels}.js` |

`static/js/mapping.js` is the **single source** for action→position/animation,
interest→expression intensity, decision→one-shot effect, and speech-bubble
rules. `static/assets/` is intentionally empty (`assets/README.md`); the room
and character textures are all generated procedurally by `room_scene.js` via
Phaser `Graphics.generateTexture()` (see DESIGN.md, "where the plan and the
actual implementation diverged").

### `tests/` (names/scope only)

`conftest.py` provides the `data_paths` (a temporary, initialized data
directory) and `config` (mock-mode configuration) fixtures. 242 tests verify
the following, module by module: config loading (`test_config.py`), paths/data
directory initialization (`test_paths.py`), the storage layer
(`test_storage.py`, `test_inbox.py`, `test_outbox.py`), locking
(`test_lock.py`), the LLM client
(`test_llm.py`), the wake loop (`test_loop.py`, `test_loop_m2m3.py`,
`test_loop_outbox.py`), prompt
normalization (`test_prompts.py`), web tools (`test_webtools.py`), offline
action expansion (`test_actions_m2.py`), serendipity
(`test_context_serendipity.py`), revealed interest (`test_revealed.py`),
the sandbox (`test_sandbox.py`), the tool-use loop (`test_tools_loop.py`),
the observer-request tool (`test_outbox_tool.py`), autosave
(`test_autosave.py`),
the wiki (`test_wiki.py`), preemption (`test_preempt.py`), reports
(`test_report.py`), the scheduler (`test_scheduler.py`), the web API
(`test_web_api.py`), the MCP server (`test_mcp_server.py`), and skills
(`test_skills_m8.py`).

## Data directory (`data/`, default `./data`, a separate git repo from the source repository)

```
data/
├── .git/                      # git repository dedicated to the soul's growth history
├── .gitignore                 # the "not committed" list below
├── SOUL.md                    # identity — written only by soul.py. Committed.
├── state.json                 # UI snapshot. Not committed (volatile).
├── agent.lock                 # pid+timestamp lock. Not committed.
├── journal/steps-YYYY-MM.jsonl  # step records, monthly rotation. Committed (alongside reports).
├── notes/step-XXXXXX.md       # ACT outputs. Committed (alongside reports).
├── wiki/<slug>.md             # wiki sources (frontmatter + body + [[links]]). Committed (wiki.py).
├── index/wiki.sqlite3         # derived wiki FTS5 + link-graph index. Not committed (rebuildable).
├── skills/<name>/manifest.json, skill.py  # self-authored skills. Committed (skills.py).
├── sandbox/                   # throwaway scratch for skill execution. Not committed.
├── home/                      # persistent working directory (cwd) for code_experiment. Files the agent writes via relative paths persist across steps; resolved outbox attachments are copied to home/attachments/<req-id>/. Committed periodically (autosave.py).
├── reports/YYYY-MM-DD.md      # daily retrospectives. Committed (report.py).
├── inbox/{pending,delivered}.jsonl, inbox.lock  # observer message queue. Committed periodically (autosave.py).
├── outbox/requests.jsonl      # agent→observer requests (agent appends via the observer_request tool). Committed periodically (autosave.py).
├── outbox/resolutions.jsonl   # observer responses (web appends; resolved/declined/ignored/reopened). Same autosave coverage.
├── outbox/attachments/<req-id>/<file>  # files the observer attached on resolve (web, create-only).
├── outbox/seen.json, outbox.lock  # agent-side resolution cursor + advisory lock.
├── chat/recorded.jsonl        # only record=true conversations. Committed periodically (autosave.py).
├── transcripts/<step_id>.jsonl  # full per-step LLM round-trips. Not committed (size/noise).
├── control/chat.json, paused_step.json  # inter-process signals. Not committed.
└── logs/agent.log             # operational logs. Not committed.
```

**Commit-target summary** (the list `paths.py:DATA_GITIGNORE` explicitly
excludes: `state.json`, `index/`, `control/`, `logs/`, `agent.lock`,
`sandbox/`, `transcripts/`): everything else is committed, but each commit
routine adds only its own designated targets — `soul.py` adds only SOUL.md,
`wiki.py` only the relevant page md, `skills.py` only the relevant skill
directory, `report.py` commits `reports/ journal/ notes/` together once a
day, and `autosave.py` sweeps up the accumulating history the others don't
own (`journal/ notes/ home/ inbox/ outbox/ chat/`) every
`agent.autosave_every_steps` steps.

## API endpoints (`soul/web/api.py:build_router`)

| Method | Path | Description |
|---|---|---|
| GET | `/api/state` | Current `state.json` snapshot + `stale` flag (true if nothing has been heard by `next_wake_at`+`step_timeout_minutes` — a step in progress is not stale) + `stale_at` (that reference time). |
| GET | `/api/events` | SSE. Pushes the same snapshot as `event: state` on every `state.json` change. |
| GET | `/api/steps?limit=50` | Journal step list (newest first). |
| GET | `/api/step/{step_id}` | Step record + the body at `content_path`. |
| GET | `/api/step/{step_id}/transcript` | Full LLM round-trip for that step (the thought process). |
| GET | `/api/soul` | Current full SOUL.md + last update time. |
| GET | `/api/soul/history` | List of commits that touched SOUL.md (newest first). |
| GET | `/api/soul/diff/{commit}` | Unified diff that a specific commit introduced to SOUL.md. |
| GET | `/api/reports` | List of dates for which reports exist (newest first). |
| GET | `/api/report/{date}` | Report body for that date. |
| GET | `/api/revealed` | All stated-vs-revealed interest derived metrics. |
| GET | `/api/stats?timeline=N` | Journal-wide aggregates for the stats panel: decision/action/mood distributions, interest histogram, per-step timeline (last N), chronological thread segments, error count + recent errors. |
| GET | `/api/skills` | Self-authored skill manifests (name/version/enabled/failures) + the `auto_disable_after_failures` threshold. |
| GET | `/api/wiki/pages` | Full wiki page list (slug/title/updated). |
| GET | `/api/wiki/search?q=` | FTS5 search results (slug/title/snippet). |
| GET | `/api/wiki/page/{slug}` | Page body + backlinks. |
| GET | `/api/wiki/graph` | Wiki link graph (nodes/links). |
| POST | `/api/chat` | Send a chat message (creates a session if none exists). Emits the preemption signal + immediate LLM response. |
| POST | `/api/chat/end` | End the chat session (clears the preemption signal). |
| GET | `/api/chat/{session_id}` | The session's turn list + record flag. |
| POST | `/api/inbox` (202) | Adds an observer message/gift to the pending queue. |
| GET | `/api/outbox?status=` | The agent's requests to the observer, newest first, with derived status (`open`\|`resolved`\|`declined`\|`ignored`; optional filter). |
| POST | `/api/outbox/{id}/resolve` | Multipart form (`status`, optional `note`, optional `file` — file only with resolved/declined). Appends a resolution; 404 unknown id, 409 invalid transition, 413 oversize file, 422 bad status. The API server's fourth allowed write. |

## Journal step record fields (`soul/storage/journal.py:new_step_record`)

| Field | Type (default) | Meaning |
|---|---|---|
| `id` | str | Step id in `step-NNNNNN` format. |
| `ts` | str | ISO-8601 UTC timestamp. |
| `kind` | str | `wake_step` \| `report` \| `error`. |
| `action` | str\|null | Name of the chosen action (`free_write` etc., including `skill:<name>`). |
| `topic` | str\|null | One-line topic decided by ACT. |
| `thread_id` | str\|null | `th-NNNN`. Kept identical to the previous step on `deepen` (decision-driven — the topic wording may drift between steps without breaking the thread). |
| `content_path` | str\|null | Output path (`notes/<id>.md` etc.). |
| `interest` | int\|null | 1–10, clamped. |
| `interest_delta` | str\|null | `more`\|`less`\|`same`\|`first`. |
| `mood` | str\|null | 8-value enum. If the raw value is outside the enum, the original is preserved in `mood_raw`. |
| `reason` | str\|null | The reason, written before decision. |
| `decision` | str\|null | `deepen`\|`shelve`\|`abandon`\|`new`. |
| `summary` | str\|null | One-line summary (used for the speech bubble). |
| `soul_updated` | bool | Whether SOUL.md was updated in this step. |
| `soul_commit` | str\|null | The commit hash if it was updated. |
| `serendipity_note` | str\|null | Path of the past note that serendipitously resurfaced this step. |
| `transcript_path` | str\|null | `transcripts/<id>.jsonl`. |
| `wiki_ops` | list | `[{"tool":"wiki_write","slug":...}, ...]`. |
| `web_visits` | list[str] | URLs actually visited via `web_read`. |
| `skill_used` | str\|null | Name of the self-authored skill that was executed. |
| `sandbox_backend` | str\|null | `bwrap`\|`unshare`\|`docker`\|`subprocess`\|null. |
| `preempted` | bool | Whether this step was interrupted by chat preemption. |
| `inbox_delivered` | list[str] | Ids of inbox messages delivered in this step. |
| `observer_requests` | list[str] | Ids of requests the agent left for the observer this step (`observer_request` tool). |
| `observer_resolved` | list[str] | Ids of requests whose resolution was surfaced into this step's context. |
| `llm` | dict | `{model, tokens_in, tokens_out, latency_ms}` (ACT+REFLECT combined). |
| `error` | dict\|null | `{"phase", "message", "llm_failure"}` — when `kind:"error"`. |

## `config.json` key table (`soul/config.py`)

### `llm`

| Key | Default | Meaning |
|---|---|---|
| `base_url` | `https://api.openai.com/v1` | OpenAI-compatible chat completions endpoint. |
| `model` | `gpt-4o-mini` | Model name. |
| `api_key_env` | `OPENAI_API_KEY` | Environment variable to consult when `api_key` is absent. |
| `api_key` | `null` | Directly entered key (takes top priority if present). |
| `timeout_seconds` | `120` | Request timeout. |
| `max_retries` | `3` | Retry count (backoff 1s/4s/16s). |
| `temperature` | `1.0` | Sampling temperature. |
| `max_output_tokens` | `2000` | Maximum response tokens. |
| `mock` | `false` | If true, uses FakeLLM; no API key required. |

### `agent`

| Key | Default | Meaning |
|---|---|---|
| `data_dir` | `./data` | Data directory path. |
| `mode` | `heartbeat` | `heartbeat` \| `continuous`. |
| `heartbeat_minutes` | `30` | Heartbeat-mode interval. |
| `min_step_gap_seconds` | `60` | Minimum gap between steps, common to both modes. |
| `step_timeout_minutes` | `45` | Hard step deadline (independent of the interval). |
| `context_recent_steps` | `10` | Number of recent steps to include in recall. |
| `serendipity_rate` | `0.3` | Probability of randomly resurfacing a past note. |
| `soul_max_chars` | `8000` | Maximum characters allowed when writing SOUL.md. |
| `consecutive_error_backoff` | `5` | Circuit breaker trips after this many consecutive LLM failures. |
| `autosave_every_steps` | `20` | Commit journal/notes/home/inbox/outbox/chat to the data repo every N steps (`autosave @ <step_id>`), so history is preserved even when no daily report has run yet. `0` disables. |

### `chat`

| Key | Default | Meaning |
|---|---|---|
| `record_default` | `false` | Default recording setting for new chat sessions. |
| `idle_end_seconds` | `180` | Session is treated as ended once this long has passed after the last message. |
| `preempt_max_wait_minutes` | `30` | Maximum wait before the loop forcibly attempts to resume even if the chat continues. |
| `preempt_poll_seconds` | `2` | Interval at which the loop polls for preemption release. |

### `sandbox`

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Whether `code_experiment` runs. |
| `timeout_seconds` | `10` | Sandbox execution timeout. |
| `backend` | `auto` | `auto`\|`bwrap`\|`unshare`\|`docker`\|`subprocess` can be forced. |

### `skills`

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | On/off switch for the entire self-authored skill system. |
| `timeout_seconds` | `20` | Skill execution timeout. |
| `auto_disable_after_failures` | `3` | How many consecutive failures trigger auto-disable. |

### `web_actions`

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Whether `web_explore`/web tools are exposed. |
| `http_timeout_seconds` | `20` | Web request timeout. |
| `max_page_kb` | `500` | Maximum bytes received by `web_read` (KB). |

### `observer_requests`

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Whether the `observer_request` tool is offered to ACT. Pending resolutions still reach the agent when disabled. |
| `max_open` | `5` | Maximum simultaneously open requests; at the cap the tool returns a neutral error string. Declined/ignored requests free a slot. |
| `max_attachment_mb` | `20` | Upload size cap for resolve attachments (413 beyond it). |

### `knowledge`

| Key | Default | Meaning |
|---|---|---|
| `max_tool_rounds` | `5` | Maximum ACT tool-loop rounds (a final tool-less call is forced when exceeded). |
| `fts_snippet_len` | `200` | Wiki search snippet length. |

### `report`

| Key | Default | Meaning |
|---|---|---|
| `time` | `22:00` | Daily report trigger time (local). |
| `timezone` | `Asia/Seoul` | `zoneinfo` timezone name. |
| `language` | `ko` | Report language (`ko`\|`en`\|`ja` supported; other codes are passed to the prompt as-is). |

### `web`

| Key | Default | Meaning |
|---|---|---|
| `host` | `127.0.0.1` | API server bind address. |
| `port` | `8000` | API server port. |
| `sse_check_ms` | `1000` | Interval (ms) at which SSE polls `state.json` mtime. |
| `allowed_networks` | `[]` | List of CIDRs allowed to connect (e.g. `["192.168.0.0/24", "::1/128"]`). Empty means no filtering — the default `127.0.0.1` bind is already local-only, so set this together when opening host to `0.0.0.0` etc. When the list is non-empty, any IP outside it or any undeterminable address gets 403 (fail-closed). |
