[English](PLAN.md) | [한국어](PLAN.ko.md)

# Plan Instruction — "Soul Tamagotchi" (raising an autonomous agent)

> Use this entire document as the plan-mode prompt for Claude Code.
> The deliverable at this stage is an **implementation plan**. Do not write code first.

## 1. Project goal

Build an **autonomous agent** that finds its own interests, digs deep when something hooks it, drops things when bored, and — through the accumulation of those choices — develops its own grain (a "soul").
No human seeds a direction in advance. Its personality starts as a completely blank slate,
and the agent becomes itself as it lives.

Then build a **web service where a person can observe and interact with this being like raising a tamagotchi**.

## 2. Hard constraints (the plan must honor these)

1. SOUL.md / MCP and the like may be used.
2. **Actions happen via external LLM API calls.** Use an OpenAI-compatible endpoint
   (chat completions), with local Ollama as the default target (`base_url` configurable). Do not lock in
   to any specific vendor — split `base_url` / `model` / `api_key` out into configuration.
3. **The agent loop is a local Python script.** Everything, daemon/scheduler included, runs locally.
   No external agent frameworks (heavy scaffolding of the LangChain sort) — implement it directly with the
   standard library plus minimal dependencies.
4. **Provide a web-based viewing service.** The agent's current state, activity, and history must be
   visible in a browser.
   - Build it as an **API server + web frontend split architecture**. The web UI is merely one client
     of the API; consider from the start the scenario where this program later runs as a server and a
     mobile app connects to the same API (do not mix UI-only logic into the API).
5. **The web UI is not just a dashboard but a "raising" interface.** Like a tamagotchi/Gather Town,
   the agent exists as a character in a small space (a room/village) where you can see what it is
   doing right now, and its mood and interest state show through expressions/behavior. Tables and log
   listings must not be the primary screen (raw logs only as a secondary view).

## 3. Soul philosophy (design principles)

- **Blank-slate start**: SOUL.md (or an equivalent identity file) starts nearly empty.
  No tastes, personality, or interests are seeded in.
- **Interest is a real signal**: every step, the agent rates its own interest (1–10) and
  decides on one of deepen / shelve / abandon / new. The accumulation of these decisions becomes its personality.
- **Ownership of self-description**: only the agent itself rewrites SOUL.md. Changes are version-
  controlled with git so the "growth history of the soul" can be seen as diffs.
- **Honest framing**: this is a system that *simulates* self-directed interest, not a
  literal injection of a soul. UI copy must not overstate it either.
- **Minimal observer intervention**: even if the web UI includes human interactions (talking to it,
  gift-like "tossing it something to read", etc.), the agent's freedom to ignore them is guaranteed.

## 4. System components (to be made concrete in the plan)

### A. Agent core (Python)
- **Wake loop**: recall (load SOUL.md + recent records) → execute one action → self-rate interest →
  decide (deepen/shelve/abandon/new) → save the record → if durable, update SOUL.md + git commit.
- **Scheduling**: run on a heartbeat interval + generate a first-person retrospective report daily at a designated time in a designated language.
  The plan must specify whether to use an in-Python scheduler or system cron, and how to prevent overlap (lock).
  - **Also support a continuous mode (infinite loop)**: besides interval execution like "once every 30 minutes",
    a mode that starts the next step as soon as the current one finishes. Switching between interval mode ↔ continuous mode is a config setting.
- **Chat preemption**: when the user requests a conversation while the agent is doing background work,
  the in-progress LLM work is finished only up to the current point, then paused, and the user conversation is handled first.
  When the user signals the end of the conversation or a timeout elapses, it automatically returns to the original work.
  The plan must specify how the state at the pause point is preserved and restored.
- **Action space**: propose what the initial list of things a blank-slate being can actually "do" should be
  (e.g. web search/reading, writing, organizing notes, code experiments), and how to sandbox them safely.
  Design it neutrally so the action space itself does not steer the personality.
  - **Web search**: implement it simply and directly on top of DuckDuckGo (no separate API key needed).
  - **Paper search**: add paper search and abstract reading via the arXiv API.
- **Skill system (self-enhancement)**: let the agent write and register its own skills (action-extension
  modules) to widen its own action space. However, **built-in skills are immutable** (read-only), and
  self-made skills are stored in a separate directory under git version control. The plan must include how
  self-made skills are loaded/executed with sandboxing and failure isolation (the loop survives even if a skill dies).
- **LLM client**: OpenAI-compatible. Includes retries, timeouts, and context budget management.

### B. State and memory storage
- Include in the plan the storage choice (SQLite vs JSONL etc.) and schema for activity records
  (per-step logs), interest trends, and reports.
- SOUL.md + git history = identity. Storage = event record. Keep this separation of roles.
- Keep the state records, SOUL.md, and everything else the target agent stores in a single directory,
  so it can be imported wholesale into another AI (like Claude Code) for quick diagnosis when problems occur.

### C. Web service
- **Backend**: an API that reads agent state (suggest something lightweight like FastAPI). Compare
  real-time update mechanisms (SSE vs WebSocket vs polling) and pick one.
  - Design the API independently of the web UI (in anticipation of other clients such as mobile apps).
    Expose all "raising" interactions — chat request, chat end, state subscription, etc. — through the API too.
- **Frontend**: a small space with a character in it. Minimum requirements:
  - The current activity is expressed through the character's behavior/position/speech bubble (e.g. sitting at a desk means "reading")
  - Interest and mood are visually apparent (facial expressions, effects, etc.)
  - A "soul growth" view: the current SOUL.md + a git diff timeline
  - Viewing the daily retrospective report (first-person Korean)
  - Make it possible to talk with the agent too (but whether this gets recorded or not is left to the user's discretion)
  - (Optional) light interactions: talking to it / giving it something to read — delivered on the agent's
    next wake as "something the observer left", with the agent free to respond or not
  - Propose the technology choice (pure HTML/JS vs a lightweight framework vs a 2D engine like Phaser) with trade-offs. Prefer something simple that runs quickly over introducing an excessive game engine.

## 5. Questions the plan must answer

The plan document must include a decision and rationale for each of the following:

1. Project directory structure and module separation (agent / storage / web / config)
2. A draft prompt structure for one wake step — how to get self-assessment and decisions as
   structured output (JSON) without breaking the blank-slate philosophy
3. The schema for interest/decision data, and the rules by which the web UI maps it to character state
4. Process composition for the agent loop and the web server (single process vs separate + shared storage)
5. Failure scenarios: LLM down, loop crash, step overlap, git commit contention — a response for each
6. Config file entries — **format confirmed as JSON**. Specify the entries in the plan (base_url, model, api_key,
   heartbeat interval vs continuous mode, chat timeout, timezone, report time, etc.)
7. Implementation of chat preemption — delivering the loop interruption signal, preserving state at the pause point, resuming after timeout
8. Self-made skills: interface specification, storage location, loading mechanism, sandboxing and failure isolation
9. Implementation order (milestones): minimal loop → storage → reports → API → UI, with completion criteria per stage
10. Test strategy: how to verify loop logic with LLM mocking

## 6. Non-goals (not doing now)

- Multi-agent, agent-to-agent conversation
- Cloud deployment, auth/multi-user
- Voice, 3D
- Compatibility with Hermes

## 7. Deliverable format

- An **implementation plan** answering all the questions in §5 above (including per-milestone, file-level task lists)
- Points that are uncertain or need a user decision are presented separately in a "Questions" section
- No code is written before the plan is approved

---

# Implementation Plan (Part 2 — answers to the spec above)

> Decisions and rationale for the 10 questions in §5 above. Where the answers live: 1→P1, 2→P2, 3→P4, 4→P5, 5→P5,
> 6→P6, 7→P7, 8→P8, 9→P9, 10→P10.

## P0. Confirmed items and key decisions

**User-confirmed items:**
- LLM: external OpenAI-compatible API as the default target (base_url/model/api_key split into config, switchable to Ollama)
- Frontend: **Phaser 3** (CDN + pure JS, no build tooling)
- Action space: offline actions + **web search (direct DuckDuckGo implementation) + arXiv paper search** (included in v1 per spec revision)
- Art: CC0 pixel asset packs (Kenney.nl etc.)
- Heartbeat default 30 minutes (+ config switch to continuous mode)
- Prompts in **English**, daily report in first-person Korean
- code_experiment/skill execution: isolate when possible — bwrap/unshare natively on Linux, Docker on Windows, plain subprocess as the last-resort fallback
- **Interest-philosophy refinements (from review)**: separate measurement of stated/revealed interest, relative anchors, environmental serendipity, reason→decision field order
- **Knowledge wiki + MCP**: a searchable wiki (md originals + SQLite FTS index) + a read-only MCP server for external AIs
- **Thought-process observability**: preserve full per-step LLM round-trip transcripts, viewable via UI/API/MCP

| Item | Decision | Rationale |
|---|---|---|
| Storage | JSONL + Markdown + state.json (SQLite only for the derived wiki index) | "Import one directory wholesale for diagnosis" → text that humans/AIs can read as-is. Data volume is tiny |
| Scheduling | In-Python loop (long-running) + lock file, serving both interval/continuous modes | No cron on Windows. A resident process is also essential for continuous mode and preemption |
| Processes | Agent loop / API server **split into 2 processes**, sharing the data directory | Failure isolation (UI survives if the loop dies), keeps sync loop + async web concurrency simple |
| API first | Expose every interaction (chat start/end, subscription, gifts) via REST/SSE; the web UI is one client among others | In anticipation of other clients such as mobile apps (spec §2.4) |
| Real-time updates | SSE (EventSource) | Fits low-frequency, one-way events. WebSocket bidirectionality unnecessary, polling wasteful |
| Chat | API server calls the LLM directly and immediately + **preemption protocol** (P7) + user toggle for recording | Reconciles instant responses with "the agent stops what it was doing to respond" |
| Config | **JSON** (`config.json`, stdlib `json`) | Confirmed by spec §5.6 |
| Dependencies | 4 packages: `fastapi`, `uvicorn`, `httpx`, `mcp` | The agent core is standard library except httpx. sqlite3/xml/html parsers are stdlib |

## P1. Directory structure and module separation

### Source repository (`tamagotchi/`)

```
tamagotchi/
├── config.example.json        # committed / config.json is .gitignore'd
├── requirements.txt           # fastapi, uvicorn, httpx, mcp (dev: pytest)
├── run_agent.py               # entry point: agent loop (--once, --mock flags)
├── run_web.py                 # entry point: API server
├── run_mcp.py                 # entry point: knowledge MCP server (stdio, read-only)
├── scripts/start_agent.ps1    # while-loop wrapper with automatic crash restart
├── scripts/start_web.ps1
├── soul/                      # Python package
│   ├── config.py              # config.json load+validate (dataclass)
│   ├── paths.py               # data directory paths/initialization
│   ├── agent/
│   │   ├── loop.py            # wake step orchestration (the heart) + preemption checkpoints
│   │   ├── scheduler.py       # interval/continuous mode loop + report-time trigger
│   │   ├── llm.py             # OpenAI-compatible client (retries/timeouts/tool loop/transcripts)
│   │   ├── prompts.py         # English prompt templates (the core of the blank-slate philosophy)
│   │   ├── actions.py         # built-in action definitions + side effects (read-only = belongs to source repo)
│   │   ├── webtools.py        # web_search (DuckDuckGo)/web_read/arxiv_search tools
│   │   ├── skills.py          # self-made skill loading/registration/failure isolation (P8)
│   │   ├── skill_runner.py    # skill execution runner (via subprocess, sandbox ladder)
│   │   ├── preempt.py         # chat preemption: watch control files, save/restore snapshots (P7)
│   │   ├── context.py         # context assembly (SOUL.md+recent steps+thread+inbox+serendipity)
│   │   ├── soul.py            # SOUL.md read/write + git commit
│   │   ├── report.py          # daily first-person Korean retrospective
│   │   ├── sandbox.py         # isolation backend ladder (shared by code_experiment/skills)
│   │   └── lock.py            # agent.lock (pid+timestamp, stale takeover)
│   ├── storage/
│   │   ├── journal.py         # steps JSONL append/tail + revealed_interest derived metrics
│   │   ├── state.py           # state.json atomic writes (tmp+os.replace)
│   │   ├── inbox.py           # pending→delivered queue
│   │   ├── control.py         # data/control/ signal files (chat.json, paused_step.json)
│   │   └── chatlog.py
│   ├── knowledge/
│   │   ├── wiki.py            # wiki: md-original CRUD + [[link]] parsing + SQLite FTS5 index + rebuild
│   │   ├── tools.py           # LLM function-calling tool schemas+dispatcher (wiki+web+skill)
│   │   └── mcp_server.py      # read-only MCP server (for external AI diagnosis)
│   └── web/
│       ├── server.py          # FastAPI app + StaticFiles (UI is just static files, no UI logic in the API)
│       ├── api.py             # REST routes
│       ├── events.py          # SSE (watches state.json mtime)
│       ├── chat.py            # chat sessions + preemption signal emission + record toggle
│       ├── gitview.py         # SOUL.md git log/diff (read-only)
│       └── static/            # web client (one client of the API)
│           ├── index.html     # Phaser 3 CDN <script>
│           ├── js/{main,api,room_scene,mapping,panels}.js
│           └── assets/        # CC0 pixel sprites/tiles
└── tests/                     # conftest, fake_llm + per-module tests
```

### Data directory (the agent's "body", default `./data/`, gitignored)

**Its own git repository** — separate from the source; importing just `data/` wholesale into another AI enables diagnosis.

```
data/
├── .git/                      # git dedicated to the soul's growth history
├── SOUL.md                    # identity (agent-only edits, seeded nearly empty)
├── state.json                 # current snapshot for the UI (not committed)
├── journal/steps-YYYY-MM.jsonl  # monthly rotation, one line per step
├── notes/                     # activity outputs, .md
├── wiki/                      # knowledge base: one md per page, [[link]] net (git committed)
├── index/wiki.sqlite3         # FTS5+link-graph derived index (not committed, rebuildable)
├── skills/<name>/             # self-made skills: manifest.json + skill.py (git committed) — P8
├── sandbox/                   # code_experiment working directory
├── reports/YYYY-MM-DD.md      # daily Korean retrospective
├── inbox/{pending,delivered}.jsonl  # observer message/gift queue
├── chat/recorded.jsonl        # only conversations recorded with consent
├── transcripts/step-*.jsonl   # full per-step LLM round-trips (chain of thought — P2.5)
├── control/                   # inter-process signals: chat.json, paused_step.json (not committed)
├── logs/agent.log             # operations log
└── agent.lock
```

Role separation: SOUL.md + git = identity / journal = event record. Only `soul.py` writes SOUL.md.
Commit targets: SOUL.md, notes/, wiki/, skills/, reports/ (+ a once-daily companion journal commit at report time).

## P2. Wake step prompt structure

```
recall (context.py) → [call 1 ACT] choose+perform action (tool-use loop, max 5 rounds)
                → save output to notes/
                → [call 2 REFLECT] interest self-assessment+decision JSON (no tools)
                → journal append → state.json update → (on soul_update) SOUL.md update+commit
```

Why split action/assessment: mixing free prose with structured JSON is fragile to parse, and assessing a finished output is more honest.

### Blank-slate prompt principles (English prompts)
- The system prompt describes only the situation and mechanics. No personality adjectives ("curious" etc.), no example topics
- The action list is **randomly shuffled every step** (prevents position bias)
- The four decisions are presented only as symmetric, one-line, neutral definitions
- The interest scale anchors only the endpoints (1 = not drawn at all, 10 = strongly drawn) + a **relative anchor alongside**: also ask "compared to your previous assessment, are you more/less/similarly drawn?" (`interest_delta`) to counter the central clustering (bunching at 6–8) of LLM self-assessment and produce real rises and falls in the time series
- Place **reason before decision** (reason→decision order mitigates post-hoc rationalization)
- soul_update is "true only when something durable has emerged; when uncertain, false is the default"

### ACT response JSON
```json
{"action": "<one from the list>", "topic": "<one line>", "content": "<full markdown of the result>"}
```

### REFLECT response JSON (field order deliberate: reason precedes decision)
```json
{"interest": 1-10, "interest_delta": "more|less|same|first",
 "mood": "neutral|curious|excited|calm|bored|frustrated|tired|proud",
 "reason": "...", "decision": "deepen|shelve|abandon|new", "summary": "<one line>",
 "soul_update": {"update": false, "content": "<new full SOUL.md text when true>", "reason": "..."}}
```
The REFLECT user message presents "the previous interest assessment in this thread" to give interest_delta a comparison baseline. If the delta and the absolute value contradict, preserve both verbatim — the contradiction is itself observational data.

### P2.5 Thought-process (chain of thought) observability

- **Transcript preservation**: `llm.py` saves every LLM round-trip of a step (full messages, per-tool-round tool_calls and results, raw responses) to `data/transcripts/step-XXXXXX.jsonl` (1 call = 1 line). The journal links via `transcript_path`. Reconstructible: what went into recall and what came out
- **Reasoning-token capture**: if the response contains a `reasoning_content`/`reasoning` field, preserve it as-is. If absent, do not elicit it via prompting (a forced "describe your thinking" field harms performance and neutrality — the reason field is the minimal explicit rationale)
- **Three viewing paths**: ① a "thought process" tab in the UI step detail ② `GET /api/step/{id}/transcript` ③ MCP `read_transcript(step_id)`
- Not git-committed (volume/noise), monthly subfolders. Chat is preserved the same way when record=true

### Separating stated vs revealed interest (the core of the philosophy refinement)

Treat self-reported interest as **self-report (stated)**, and derive **the real signal from the accumulation of behavior (revealed)** separately — countering the positivity bias and confabulation of LLM self-assessment.

- Revealed metrics (derived from the journal by a pure function, no LLM involved): thread persistence length / whether and how often the agent actually returns after a shelve / how frequently the same topic reappears
- Where it is computed: `revealed_interest(steps)` in `journal.py` — computed on query, not stored
- The stated-vs-revealed **gap is first-class observational data**: exposed side by side in the API and UI, and included in the daily report context so the agent sees the gap between its own words and actions for itself

### Environmental serendipity (mitigating model-prior convergence)

The same model with the same blank slate risks converging to the model's default persona → supply randomness from the environment without seeding topics (individuality = prior + the contingency of the path):
- Shuffling the action list
- **Random resurfacing of past notes**: during recall assembly, with low probability (`serendipity_rate` 0.3), include one past note as "a note you wrote before"
- The observer inbox is by design already external contingency
- All of it is topic-neutral (chosen by random draw, not by content) — no conflict with the blank-slate philosophy

### 3-stage JSON robustness fallback
`response_format: json_object` → on failure, regex-extract the outermost `{…}` → one corrective re-call → record an error step and skip. interest is clamp(1,10); out-of-enum values normalize to neutral with `raw` preserved.

## P3. Action space v1 (neutral verbs)

Built-in actions: `free_write / revisit_notes / organize_notes / thought_experiment / code_experiment / web_explore / read_inbox (only when inbox is non-empty) / rest` + self-made skills as `skill:<name>` (only enabled ones, listed neutrally)

### Web tools (available in the tool-use loop during web_explore)
- `web_search(query)`: directly parses the DuckDuckGo HTML endpoint (html.duckduckgo.com/html), no API key needed. Returns top-N titles/URLs/snippets
- `web_read(url)`: httpx fetch + body text extraction via the stdlib html.parser, `max_page_kb` cap (default 500KB), 20-second timeout
- `arxiv_search(query)`: arXiv Atom API (export.arxiv.org/api/query) + `xml.etree` parsing — returns titles/authors/abstracts
- Safety: no domain blocklist (neutrality); instead, size and time caps, and visited URLs recorded in the journal. Search terms and URLs are entirely the agent's choice

### code_experiment / skill execution isolation — backend ladder (`sandbox.py`, `backend:"auto"`)
1. **Linux native (first choice, no Docker needed)**: `bwrap` (bubblewrap) — `--unshare-all --die-with-parent --bind data/sandbox /work ...`, unprivileged namespace isolation (blocks network/PID/mounts), no daemon, ~ms overhead. If bwrap is absent, fall back to `unshare --user --net --pid --map-root-user`. On distros that block unprivileged userns, move to the next rung
2. **Docker** (when `docker info` succeeds): `--network none`, volume mount, `--memory`/`--pids-limit` — the only strong isolation on Windows
3. **Plain subprocess fallback**: cwd-confined, minimized environment variables, timeout — explicitly not isolation

Common: timeout (default 10 seconds), stdout/stderr capture. The selected backend is recorded in the startup log and in the journal's `sandbox_backend`.

## P3.5 Knowledge store — wiki (a searchable net)

The response to the problem that markdown notes alone are not searchable.

### Storage structure (original md + derived SQLite — diagnosability and searchability both)
- **Originals**: `data/wiki/<slug>.md` — frontmatter + body, an llm-wiki-style net via `[[other-page]]` links. Git committed (knowledge growth is also observable as diffs)
- **Derived index**: `data/index/wiki.sqlite3` — `pages`, `links(src,dst)` (backlink graph), FTS5 `pages_fts`. **Always fully rebuildable from md** (`rebuild_index()`, automatic rebuild on startup when an mtime mismatch is detected). Not committed
- sqlite3 and FTS5 are stdlib — 0 dependencies

### Agent access: function-calling tool loop
Make the ACT call a **small tool-use loop** based on standard chat completions `tools` (no framework needed):
- 4 wiki tools: `wiki_search` (FTS) / `wiki_read` (body+backlinks) / `wiki_write` (create/update, [[link]] auto-indexing) / `wiki_backlinks`
- Loop: tool_calls → dispatch → append results → re-call, up to `max_tool_rounds` (default 5), then force the final ACT JSON
- Tool descriptions are neutral ("store something you want to find again"); writing or not writing is the agent's choice
- REFLECT gets no tools (prevents assessment contamination). `wiki_ops` recorded in the journal

### External access: read-only MCP server (`run_mcp.py`)
For structured diagnosis by external AIs such as Claude Code. Official `mcp` Python SDK.
- Tools: `wiki_search`, `wiki_read`, `wiki_list`, `read_soul`, `query_journal(limit, since)`, `read_report(date)`, `read_transcript(step_id)`
- **Read-only** — preserves the principle that the agent process is the sole writer. SQLite is also opened with a read-only connection
- Registration: `claude mcp add soul-wiki -- python run_mcp.py --data-dir ./data`

## P4. Journal schema & UI mapping

### Step record (one JSONL line)
```json
{"id":"step-000123","ts":"...","kind":"wake_step|report|error","action":"...","topic":"...",
 "thread_id":"th-0007","content_path":"notes/....md","interest":7,"interest_delta":"more",
 "mood":"curious","reason":"...","decision":"deepen","summary":"...",
 "soul_updated":true,"soul_commit":"abc1234","serendipity_note":"notes/....md",
 "transcript_path":"transcripts/step-000123.jsonl",
 "wiki_ops":[{"tool":"wiki_write","slug":"..."}],"web_visits":["https://..."],
 "skill_used":null,"sandbox_backend":null,"preempted":false,
 "inbox_delivered":["in-0004"],"llm":{"model":"...","tokens_in":0,"tokens_out":0,"latency_ms":0},"error":null}
```

Thread rules: deepen→keep the same thread_id, shelve→kept in the state.json shelved list, abandon/new→new thread_id on the next step.

### state.json (single snapshot, atomic replacement)
`status(awake|idle|chatting|error), last_step summary, current_thread{topic,steps,interest_series}, shelved_threads, revealed{top_threads,stated_vs_revealed_note}, next_wake_at, today_report, updated_at`

### Mapping rules (single source: `mapping.js`)
- **Action→position/animation**: free_write=desk, writing / revisit_notes=bookshelf, reading / organize_notes=bookshelf, tidying / thought_experiment=rug by the window, thought cloud / code_experiment=computer, typing / web_explore=laptop by the window, scrolling / skill:*=workbench, tinkering / read_inbox=mailbox, opening / rest=bed, Zzz / chatting=at the door, talking motion / idle=wandering / stale·error=stopped at center + "…"
- **interest→expression intensity**: 1–3 drooping, desaturated / 4–6 neutral / 7–8 smile, sparkle / 9–10 big sparkle + particles
- **decision→one-shot effect**: deepen=lightbulb+sparks / new="!"+moving spots / shelve=slotting a note onto the shelf / abandon=crumpling paper and tossing it
- **Speech bubble**: shows last_step.summary for 30 seconds; clicking opens the full-output panel. On steps that wrote to the wiki, a "wiki note" prop on the desk glints

## P5. Process composition & failure handling

**2 processes**: `run_agent.py` (synchronous loop) + `run_web.py` (uvicorn, API server). The API server treats the data directory as read-only, exceptionally writing only inbox append + chat append + **control/chat.json** (the preemption signal). The inbox uses a small `inbox.lock` plus the protocol "the web only appends; the agent atomically moves pending→delivered at step start".

| Failure | Response |
|---|---|
| LLM down/timeout | Exponential backoff, 3 tries (1s/4s/16s, 120s timeout) → record an error step + skip. After 5 consecutive failures, circuit breaker (4x interval, restored on success). Applies equally in continuous mode |
| Loop crash | Per-step try/except isolation + `start_agent.ps1` while-loop restart (with backoff). The UI shows stale when updated_at exceeds 2x the base interval |
| Step overlap / long steps | Single process, so no internal overlap. Double launch is refused via agent.lock (pid liveness check, stale takeover). Steps exceeding the interval are not killed but run to completion, while step_timeout_minutes (hard deadline) applies separately; after completion, the next step starts automatically once min_step_gap_seconds has elapsed (scheduler rules below) |
| Git contention | The agent process is the sole writer to the data git (web and MCP only read). On commit failure, retry once; even if it fails, the files are updated → included in the next commit |
| Corrupted state.json read | Atomic replacement via tmp+os.replace; on parse failure the web keeps the previous cache |
| Report failure | Detected by the absence of the dated file, retried between every step (idempotent) |
| Skill crash | See P8 — subprocess isolation + auto-disable after consecutive failures |

**Scheduler** (`scheduler.py`): `while True: check_preempt(); check_report(); run_step(); wait()`.

**Long-running step policy — exceeding the interval is allowed, but a separate step timeout exists.**

- **Interval overrun allowed**: a step taking longer than the heartbeat interval is normal behavior and is never killed or skipped because of the interval. Instead, a **minimum separation gap** (`min_step_gap_seconds`, default 60s) is guaranteed:
  - Next step start time = `max(previous step start + heartbeat interval, previous step end + min_step_gap_seconds)`
  - Example: interval 10 min, step takes 12 min → no skip; rest 60s after completion, then the next step starts automatically
  - Example: interval 10 min, step takes 1 min → the normal 10-minute cadence from start times is kept
  - `mode:"continuous"`: only `previous step end + min_step_gap_seconds` applies, without the interval term (both modes share the same separation parameter)
- **Step timeout** (`step_timeout_minutes`, independent of the interval — e.g. interval 10 min / timeout 15 min; setting it larger than the interval is recommended): a hard deadline from step start. When exceeded, the step is aborted, the partial outputs and transcript up to that point are preserved, journaled as `kind:"error"`, `error:"step_timeout"`, and the loop proceeds to the next step. It is the final line of defense against runaways (infinite tool loops, hung skills, etc.), a safety net above individual LLM-call and tool timeouts
  - Enforcement: since the loop is synchronous, **check the deadline at every LLM-call/tool-execution boundary** — individual calls have their own timeouts (LLM 120s, tools 10–20s), so boundary checks alone keep deadline overrun within one call's length
  - Not counted toward the circuit breaker (it's "the work took long", not an API failure)
- The report-time check is common to both modes, based on `Asia/Seoul` `zoneinfo`. state.json's `next_wake_at` records the actual scheduled time computed by the rules above (the UI shows an accurate countdown)

## P6. Configuration — config.json (spec confirmed: JSON)

`config.example.json` committed / `config.json` gitignored. JSON allows no comments → each key is described in a README table next to the example.

```json
{
  "llm": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini",
          "api_key_env": "OPENAI_API_KEY", "api_key": null,
          "timeout_seconds": 120, "max_retries": 3,
          "temperature": 1.0, "max_output_tokens": 2000, "mock": false},
  "agent": {"data_dir": "./data", "mode": "heartbeat", "heartbeat_minutes": 30,
            "min_step_gap_seconds": 60, "step_timeout_minutes": 45,
            "context_recent_steps": 10,
            "serendipity_rate": 0.3, "soul_max_chars": 8000,
            "consecutive_error_backoff": 5},
  "chat": {"record_default": false, "idle_end_seconds": 180,
           "preempt_max_wait_minutes": 30, "preempt_poll_seconds": 2},
  "sandbox": {"enabled": true, "timeout_seconds": 10, "backend": "auto"},
  "skills": {"enabled": true, "timeout_seconds": 20, "auto_disable_after_failures": 3},
  "web_actions": {"enabled": true, "http_timeout_seconds": 20, "max_page_kb": 500},
  "knowledge": {"max_tool_rounds": 5, "fts_snippet_len": 200},
  "report": {"time": "22:00", "timezone": "Asia/Seoul", "language": "ko"},
  "web": {"host": "127.0.0.1", "port": 8000, "sse_check_ms": 1000}
}
```

api_key resolution: `api_key` written directly → `api_key_env` environment variable → if neither, operate without a key
(the Authorization header is omitted — supports keyless endpoints like local Ollama; spec revision 2026-07-16).

## P7. Chat preemption

**Signal delivery = control files** (minimizes IPC in the split-process architecture, same pattern as the state.json bus):

1. **Chat start**: on receiving the first message at `POST /api/chat`, the API server atomically writes `data/control/chat.json` `{active:true, session_id, started_at, last_message_at}`. The chat response itself is an immediate, direct LLM call by the API server (current SOUL.md + recent steps + session turns) — the user does not wait
2. **Loop pause (only up to the current point)**: the agent loop checks `chat.json` **at every LLM-call boundary** (before ACT starts / between tool rounds / before REFLECT). If active, the in-flight call is completed, then it stops at that point
3. **State preservation**: on pause, a snapshot is saved to `data/control/paused_step.json` — `{step_id, phase:"act|tools|reflect", messages_so_far, tool_rounds_done, act_result (if any), started_at}`. state.status="chatting" is updated (the character comes to the door)
4. **Resume**: when the user calls `POST /api/chat/end`, or `last_message_at` exceeds `idle_end_seconds` (default 180s), the API server marks chat.json inactive. The loop, polling at `preempt_poll_seconds` (2s) intervals, restores the snapshot and **continues from the pause point**. If `preempt_max_wait_minutes` (30 min) is exceeded, the snapshot is restored and execution resumes even mid-chat (yielding again at the next boundary)
5. **Crash safety**: on loop restart, if paused_step.json exists, attempt restoration according to phase; if unrestorable (message mismatch etc.), record that step as an error and start a new step. The journal marks `preempted:true`
6. **Record toggle**: record=false (default) keeps the session only in server memory (lost on restart, stated in the UI); record=true goes to `chat/recorded.jsonl` + via the inbox into the next wake (the UI honestly states that only record=true conversations become "memories")

## P8. Self-made skill system

**Built-in skills = the source repo's `actions.py`/`webtools.py`** — the agent can write only to the data directory, so they are structurally immutable (satisfies the read-only requirement).

- **Storage location**: `data/skills/<name>/` — `manifest.json` + `skill.py`. Version-controlled in the data git (the birth and revision of skills are part of the growth history too)
- **Interface specification**:
  - `manifest.json`: `{"name", "description", "entry": "skill.py", "version": 1, "enabled": true, "failures": 0, "created_at"}`
  - `skill.py`: `def run(params: dict) -> dict` — returns `{"output": "<markdown>"}`. Only standard-library imports allowed (the runner checks)
- **Registration**: a `skill_write(name, description, code)` tool is provided in the ACT tool loop (neutral wording: "define a new activity you can do later"). On success, it appears in the action list as `skill:<name>` from the next step — creating/using/discarding it is entirely the agent's choice
- **Loading/execution**: never imported. `skill_runner.py` runs it in a **separate subprocess** (passing through P3's sandbox ladder as-is) — params as stdin JSON, result as stdout JSON. Complete memory separation from the agent process
- **Failure isolation**: timeout (`skills.timeout_seconds` 20s)/exception/non-JSON output → the step proceeds normally with a "skill failure result" rather than an error (the loop never dies), and the manifest's `failures`++ increments. On reaching `auto_disable_after_failures` (3), set `enabled:false` — the disablement is announced in the next context (fixing it or abandoning it is also the agent's choice)
- **Security limits stated**: in plain-subprocess fallback mode, the README and startup log honestly state that this is not strong isolation

## P9. Milestones (with completion criteria)

**M0 — Scaffolding**: requirements.txt, .gitignore, config.example.json, `config.py`, `paths.py`, tests/conftest.py. `init_data_dir()`: data/ tree + nearly-empty SOUL.md seed + git init/initial commit.
✓ data/ created, config load tests green.

**M1 — Minimal wake loop (mock)**: llm.py, prompts.py, context.py, loop.py, actions.py (free_write/rest), soul.py, lock.py, journal.py, state.py, fake_llm.py, run_agent.py (`--once --mock`).
✓ 1 step → 1 JSONL line + notes output + full transcripts round-trips + state.json update + git commit on soul_update. pytest green including 3-stage JSON fallback tests.

**M2 — All offline actions + threads + real API**: actions.py expansion, sandbox.py (backend ladder), thread/shelved management, inbox.py.
✓ 5 consecutive steps against the real API (shortened interval), thread_id kept on deepen, sandbox timeout test, pending→delivered verification.

**M3 — Knowledge wiki + tool-use loop**: wiki.py (md CRUD, [[links]], FTS5, rebuild), tools.py, llm.py tools loop, loop.py integration.
✓ wiki_write→reflected in md+index, FTS hits, backlinks, rebuild consistency after manual md edits, FakeLLM tool_calls scenarios (including max-round forcing) green.

**M4 — Web actions**: webtools.py — web_search (DuckDuckGo)/web_read/arxiv_search, web_explore action registration.
✓ DDG/arXiv response parsing tests green with httpx MockTransport, one manual real-network check, size/timeout caps working.

**M5 — Scheduler (interval/continuous) + daily report**: scheduler.py, report.py, run_agent.py long-running mode, start_agent.ps1.
✓ Heartbeat mode runs; switching to `mode:"continuous"` chains steps at min_step_gap intervals; **long-step test** (a FakeLLM step longer than the interval → runs to completion without skip/kill, auto-resumes after min_step_gap, next_wake_at accuracy); **step-timeout test** (step_timeout exceeded → aborted at a boundary → partial outputs preserved + error:"step_timeout" recorded → next step proceeds normally, confirmed not counted toward circuit breaker); Korean first-person report generated and committed at report time; double-launch lock refusal; circuit-breaker test.

**M6 — API server + SSE + chat preemption**: server.py, api.py, events.py, chat.py, control.py, preempt.py, gitview.py, chatlog.py, run_web.py.
✓ All endpoints green under TestClient; a step occurring → SSE received within 1 second; **preemption E2E**: chat starts mid-step → the loop stops at a call boundary and status="chatting" → chat/end or timeout → snapshot-restored resume (auto-tested with FakeLLM); with record=true, recorded.jsonl + inbox reflected.

**M7 — Phaser UI**: index.html (Phaser 3 CDN), room_scene.js, mapping.js, panels.js, CC0 assets.
✓ A step occurring → character movement/animation/speech bubble reflected automatically, moves to the door when chatting, SOUL.md diff timeline, thought-process tab, wiki search/graph view, chat/gift round-trips.

**M8 — Skill system**: skills.py, skill_runner.py, skill_write tool, manifest lifecycle.
✓ FakeLLM scenarios test skill write→register→exposed in next step's list→run success/timeout/crash/auto-disable after 3 consecutive failures, all green. Loop survival confirmed.

**M9 — MCP server**: mcp_server.py, run_mcp.py.
✓ After `claude mcp add` registration, external round-trips of wiki_search/query_journal/read_soul/read_transcript. Read-only confirmed.

**M10 — Operational wrap-up**: README.md (Windows-based setup→run→observe→MCP registration reproduction steps), script polish.
✓ Reproducible in a fresh environment from the README alone.

## P10. Test strategy

- **FakeLLM** (tests/fake_llm.py): same `chat(messages, tools=None)->response` interface, response-queue scenarios — ① rising interest, consecutive deepen → thread kept + soul_update ② falling → abandon → new thread ③ broken JSON → extraction fallback ④ two consecutive non-JSON → error step ⑤ soul_update → commit hash recorded in journal ⑥ tool_calls returned → tool dispatch + max_tool_rounds forced termination ⑦ preemption: chat flag mid-step → snapshot save/restore
- **llm.py**: 429/500/timeout via `httpx.MockTransport` → backoff verified (no real network)
- **Web tools**: parsing verified against fixed DDG HTML/arXiv Atom responses via MockTransport
- **Skills**: runner + auto-disable verified with normal/timeout/crash/non-JSON-output skill fixtures
- **Wiki**: CRUD/FTS/backlinks/rebuild verified in a tmp data dir. revealed_interest tested as a pure function against journal fixtures
- **Storage/git**: commit logic verified against a real git init under tmp_path
- **Web API**: FastAPI TestClient + fake data dir; SSE tested up to receiving one event
- **E2E dev mode**: with `llm.mock=true`, the whole pipeline runs on FakeLLM — zero API cost during UI development

## P11. Verification method

1. `pytest` all green (mock-based loop/preemption/skill/storage/API logic)
2. `python run_agent.py --once --mock` → manually inspect data/ outputs, journal, state, transcripts
3. One `--once` run with a real API key → confirm an actual LLM round-trip
4. Start both processes, open `localhost:8000` in a browser → manually confirm character reactions, SOUL diffs, thought process, wiki, chat (including preemption), gift E2E
5. Force-kill the agent process → confirm the UI shows stale (failure-isolation check)
6. Register MCP via `claude mcp add` → confirm external wiki search/journal/transcript queries

## Honest framing, reflected

A fixed line at the top of the UI: plain wording on the level of "this being simulates self-directed interest". Unrecorded conversations are explicitly marked "not remembered". The stated/revealed gap is exposed, not hidden.
