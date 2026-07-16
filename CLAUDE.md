# CLAUDE.md

Guidance for Claude Code (or any AI assistant) working in this repository.

## What this is

An autonomous agent that spends discrete "wake steps" choosing and carrying out
one action, self-rating its interest, and deciding to `deepen`/`shelve`/
`abandon`/`new` — the cumulative choices are its simulated "soul" — plus a
FastAPI/Phaser web UI to observe it like a tamagotchi. Framed honestly
throughout: this *simulates* self-directed interest; it is not a literal soul.
See `DESIGN.md` for the "why", `STRUCTURE.md` for the full module/data map,
`README.md` for setup/run instructions, and `PLAN.md` for the original spec
(P0–P11) that `DESIGN.md` cross-references.

## Run / test commands

The real runtime target is **WSL Ubuntu** (`.venv-wsl`); a Windows-native venv
(`.venv`) is optional and works for tests but only ever gets the non-isolated
`subprocess` sandbox fallback (see `soul/agent/sandbox.py`).

```bash
# WSL (primary)
wsl -- bash -lc "cd /mnt/c/Users/<you>/Documents/tamagotchi && .venv-wsl/bin/python -m pytest -q"
wsl -- bash -lc "cd /mnt/c/Users/<you>/Documents/tamagotchi && .venv-wsl/bin/python run_agent.py --once --mock"

# Windows fallback
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe run_agent.py --once --mock
```

242 tests should be green. No network calls in tests — `httpx.MockTransport`
and `FakeLLM` stand in for the real LLM/HTTP; see "Test conventions" below.

## Invariants — do not break these

- **Blank-slate prompts** (`soul/agent/prompts.py`): never add personality
  adjectives, example topics, or any seeded interest to `ACT_SYSTEM_PROMPT` /
  `REFLECT_SYSTEM_PROMPT` or `soul/paths.py:SOUL_SEED`. The action list must
  stay shuffled every step (`soul/agent/actions.py:shuffled_actions`) — never
  hard-code an order. The four decisions (`deepen`/`shelve`/`abandon`/`new`)
  must stay symmetric, one-line, neutral definitions — none framed as
  preferable. The `observer_request` tool description
  (`soul/knowledge/tools.py:OUTBOX_TOOLS`) is part of this invariant: keep it
  one neutral line with a single free-form `text` parameter — no request
  categories, no examples of things to ask for, and no promise of a response
  ("a response may arrive later, or not").
- **REFLECT field order is deliberate**: `reason` must be emitted before
  `decision` in both the prompt's requested JSON shape and
  `soul/storage/journal.py:new_step_record`'s field order. Don't reorder it
  away — it's there to reduce post-hoc rationalization.
- **REFLECT gets no tools.** Only ACT runs through the tool-use loop
  (`soul/agent/llm.py:run_tool_loop`, `soul/knowledge/tools.py`). Giving
  REFLECT tool access would let it re-fetch data instead of assessing what
  already happened — don't add tools there.
- **`soul/agent/soul.py` is the sole writer of `SOUL.md`.** No other module
  should open `data/SOUL.md` for writing. Every write must go through
  `write_soul()` so it stays git-committed and size-checked
  (`agent.soul_max_chars`).
- **Write-ownership principle**: the agent loop process (`run_agent.py`) is
  the only writer of the data directory in general. The web API
  (`soul/web/`) may only write four things: `inbox/pending.jsonl` (append),
  `chat/recorded.jsonl` (append, only when `record=true`),
  `control/chat.json` (the preemption signal), and the outbox resolutions —
  `outbox/resolutions.jsonl` (append) plus attachment files under
  `outbox/attachments/` (create-only), via the resolve endpoint.
  `outbox/requests.jsonl` and `outbox/seen.json` belong to the agent loop;
  the split keeps every outbox file single-writer (`soul/storage/outbox.py`)
  — the web layer never rewrites a file, and status is derived by joining
  the two append-only logs. The MCP server
  (`soul/knowledge/mcp_server.py`) is **strictly read-only** — it opens the
  wiki SQLite index with `mode=ro` and never rebuilds it unless
  `--allow-index-rebuild` is explicitly passed. Do not add new writes to the
  web or MCP layers without re-reading `DESIGN.md` §11 first.
- **`data/` is a separate git repository from the source repo.** Never `git
  add`/commit anything under `data/` from the source repo's git — it is
  `.gitignore`'d at the top level (`tamagotchi/.gitignore: data/`) precisely
  because it has its own `.git/` (spec: "one directory importable wholesale
  into another AI for diagnosis"). If you need to touch data-repo git
  history, use `git -C data ...`, never the outer repo's git.
- **Sandbox honesty**: `soul/agent/sandbox.py`'s `SandboxResult.isolated`
  must stay `False` for the plain-subprocess fallback and `True` only for
  bwrap/unshare/docker. Don't quietly mark subprocess as isolated.

## Where things live

- `STRUCTURE.md` — full directory/module map, API endpoint table, journal
  record schema, `config.json` key table.
- `DESIGN.md` — design rationale for every major decision, each tied back to
  a `PLAN.md` section (P2, P5, P7, P8, ...), plus an honest list of where the
  implementation diverged from the original plan.
- `PLAN.md` — the original spec this project was built from.

## Test conventions

- `tests/conftest.py` provides `data_paths` (a `tmp_path`-backed, fully
  initialized data directory via `init_data_dir`) and `config` (a
  mock-mode `Config` pointed at it). Use these fixtures rather than touching
  `./data`.
- `soul/agent/fake_llm.py:FakeLLM` is the LLM test double: construct it with
  a **queue of scripted responses** (`FakeLLM([act_json, reflect_json, ...])`
  or `.enqueue(...)`); each `chat()` call pops one item. Queue items may be a
  `dict` (serialized to JSON content — the common ACT/REFLECT case), a `str`
  (raw content, for testing broken-JSON fallback), an `LLMResponse` (full
  control, e.g. `tool_calls`), or an `Exception` (to script an LLM failure).
  A wake step normally consumes exactly two queue items: ACT then REFLECT.
- `soul/agent/llm.py:LLMClient` is tested against `httpx.MockTransport`
  (see `tests/test_llm.py`) — never make real network calls in tests. The
  same pattern applies to `soul/agent/webtools.py` (DuckDuckGo/arXiv fixtures
  via `MockTransport`).
- Git-backed modules (`soul.py`, `wiki.py`, `skills.py`, `report.py`) are
  tested against a real `git init`'d repo under `tmp_path` (via `data_paths`)
  — not mocked — so commit behavior is verified for real.
- `revealed_interest()` (`soul/storage/journal.py`) is a pure function tested
  directly against hand-built journal-record fixtures, no LLM involved.

## Commit style

The source repo currently has a single "Initial commit"; no established
convention to defer to yet. Prefer small, fine-grained commits scoped to one
logical change, with a Conventional-Commits-style prefix (`feat:`, `fix:`,
`docs:`, `refactor:`, `test:`). This is distinct from the **data repo**'s own
commit messages, which follow a fixed, code-driven convention you should not
imitate for source commits: `SOUL update @ <step_id>`, `wiki: update <slug>`,
`skill: create|update|auto-disable <name>`, `report: <date>`,
`autosave @ <step_id>`.
