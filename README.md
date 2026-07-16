[English](README.md) | [한국어](README.ko.md)

# Soul Tamagotchi

## One-line project description

A personal project that builds an autonomous agent which finds its own interests, digs in when hooked, and drops them when bored — repeating that choice every step — accumulating those choices into a texture of its own (a "soul"), and lets you observe and interact with it like a tamagotchi.

**In the interest of honesty**: this is a system that *simulates* self-directed interest, not a being that literally possesses a soul. All it does is self-rate its interest every step (`deepen`/`shelve`/`abandon`/`new`) and accumulate those decisions in a journal, and each of those decisions is the output of an external LLM API call. The same statement is pinned as a fixed banner at the top of the web UI.

## Requirements

- **Verified against a Windows 11 + WSL (Ubuntu) combination.** Actual Python execution happens **inside WSL** (the `.venv-wsl` virtual environment). This project's sandbox isolation ladder (`soul/agent/sandbox.py`) only provides real namespace isolation when Linux-native `bwrap`/`unshare` is available, so you need to run on WSL Ubuntu for `code_experiment` and self-authored skill execution to be meaningfully isolated.
- **The Windows-side venv (`.venv`) is optional.** Everything also works with Windows-native Python (tests included), but in that case the `sandbox.backend` ladder skips bwrap/unshare and falls back to Docker (if present) or a non-isolated plain subprocess — see the "Security honesty notes" below.
- Python 3.11+ (uses the `zoneinfo` standard library; `report.timezone` defaults to `Asia/Seoul`).
- An external LLM API key (OpenAI-compatible endpoint) — even without one, you can run the full pipeline in `--mock` mode.

## Setup

In a WSL (Ubuntu) shell:

```bash
cd /mnt/c/Users/<you>/Documents/tamagotchi

python3 -m venv .venv-wsl
source .venv-wsl/bin/activate
pip install -r requirements.txt
pip install pytest   # for tests (requirements.txt contains runtime dependencies only)

cp config.example.json config.json
```

In `config.json`, fill in at least the following (loaded and validated by `soul/config.py`):

- `llm.base_url` — an OpenAI-compatible chat completions endpoint. The default is `https://api.openai.com/v1`, but you can switch to any OpenAI-compatible server such as a local Ollama (no lock-in to a specific vendor).
- `llm.model` — the model name to use.
- `llm.api_key` or `llm.api_key_env` — the key resolution order is **(1) written directly in `llm.api_key` → (2) the environment variable named by `llm.api_key_env` → (3) if neither, operate without a key** (`soul/config.py:resolve_api_key`). Without a key, requests are sent without an Authorization header, which works as-is against key-free endpoints like a local Ollama. The default `api_key_env` is `OPENAI_API_KEY`.
- `llm.mock` — if `true`, drives the full pipeline with `FakeLLM` without a real API key (for UI development/testing, zero API cost).

**Mock mode**: without touching `config.json`, appending `--mock` to a command runs just that invocation with FakeLLM (`run_agent.py --mock`, `run_web.py --mock`). Even with no API key at all, you can verify the full flow this way (step generation → journal → state.json → transcripts).

## Running

The agent loop and the API server are **two completely separate processes** that share only the `data/` directory — if one dies, the other is unaffected (fault isolation).

### Agent loop

```bash
python run_agent.py                # long-running scheduler (heartbeat or continuous)
python run_agent.py --once         # run a single step and exit
python run_agent.py --once --mock  # one step with FakeLLM (no API key needed)
python run_agent.py --mock         # long-running with FakeLLM
```

The default is a long-running scheduler that follows `agent.mode` in `config.json` (`heartbeat` or `continuous`). It holds `agent.lock` for the lifetime of the process, so launching a second instance at the same time is refused.

### Web API server

```bash
python run_web.py            # http://127.0.0.1:8000 (config.json web.host/port)
python run_web.py --mock     # chat responses also use FakeLLM
```

### Restart wrapper scripts

`scripts/start_agent.ps1` and `scripts/start_web.ps1` are PowerShell wrappers that automatically restart with exponential backoff on crash. By default they **run with WSL's `.venv-wsl` Python** (when `wsl` and `.venv-wsl` are available); passing the `-NoWsl` switch falls back to the Windows-side venv (`.\.venv\Scripts\python.exe`). If you are running directly inside a WSL shell, you can just run `run_agent.py`/`run_web.py` without the scripts (if you need the same restart pattern, build it with a bash `while` loop).

## Observing

Visit `http://127.0.0.1:8000` (the web server must be running):

- **Room/character**: in a small Phaser 3 room, the character moves between locations like the desk/bookshelf/window/computer/workbench/mailbox/bed depending on its current behavior (`action`), and its animation changes. Interest level (1–10) shows as facial-expression intensity, and the most recent decision (`deepen`/`new`/`shelve`/`abandon`) shows as a one-shot effect (mapping rules: `soul/web/static/js/mapping.js`).
- **Soul growth (soul) panel**: the full current SOUL.md, plus a git history timeline and per-commit diffs. Only the agent process rewrites SOUL.md, and every change is committed to the data git repository, so you can view the "growth history of the soul" as diffs.
- **Thought process (step detail) tab**: browse the full ACT/REFLECT (and tool round) LLM round-trips for each step, verbatim (`GET /api/step/{id}/transcript`).
- **Wiki**: explore the `wiki_write` notes the agent wrote on its own, with search (FTS5), backlinks, and a graph.
- **Daily report**: browse, by date, the Korean first-person retrospective generated every day at the configured time (`report.time`, default 22:00 `Asia/Seoul`).
- **Chat**: you can chat with the agent. Any background work in progress pauses at an LLM-call boundary and resumes from that point once the conversation ends (preemption). **If `record` is off (the default), the conversation is not saved anywhere and is not carried into the next wake — the UI explicitly labels it "not remembered".** Only when `record=true` is it kept in `chat/recorded.jsonl` and included in the next wake's context via the observer inbox.
- **Gifts/messages (inbox)**: when an observer leaves text or a URL, it is passed neutrally into the next wake step's context as "something the observer left". Whether to react is entirely up to the agent.
- **Words vs. deeds (stated vs revealed)**: shows the self-reported interest level (stated) side by side with behavioral signals computed purely from the journal (revealed — thread persistence length, whether it returned after a shelve, topic recurrence frequency). Any gap between the two is exposed as-is, not hidden.

## MCP registration

If you register the read-only MCP server (`run_mcp.py`) with an external AI such as Claude Code, that AI can structurally diagnose this agent's data directory using the `wiki_search`/`wiki_read`/`wiki_list`/`read_soul`/`query_journal`/`read_report`/`read_transcript` tools.

```bash
claude mcp add soul-wiki -- python run_mcp.py --data-dir ./data
```

This server reads SOUL.md/journal/reports/transcripts directly as files, and opens the wiki index only through a `mode=ro` SQLite connection — it never writes to the data directory (preserving the principle that the agent process is the sole writer). If the wiki index does not exist yet, by default it does not rebuild it itself and instead returns a message telling you to run the agent once; only when `--allow-index-rebuild` is explicitly passed does it, as an exception, rebuild the derived index only (never the md sources).

## Tests

On WSL (`.venv-wsl`):

```bash
pytest
```

All 186 tests should be green. The `data_paths`/`config` fixtures in `tests/conftest.py` provide a data directory initialized under `tmp_path` and a mock-mode config, so tests never touch the real network or the real `./data`.

## Security honesty notes

- **Sandbox isolation genuinely differs by platform.** The isolation ladder in `soul/agent/sandbox.py` selects, in order: (1) Linux-native `bwrap` (or `unshare` if absent) → (2) Docker (when the daemon is up) → (3) plain subprocess. **Running on WSL Ubuntu usually selects option 1 (bwrap/unshare, with network/PID/mount namespace isolation)**, but **the Windows-native fallback is a plain subprocess, not isolation** — the code itself honestly marks it `isolated=False`, and the actually selected backend is recorded verbatim in the journal's `sandbox_backend` field and in the startup log. If you need strong isolation, use WSL or run Docker on Windows.
- The same rule applies to self-authored skill execution (`skill_runner.py`) — skills are never imported into the agent process; they always run as a separate subprocess and pass through the same sandbox ladder above.
- **DuckDuckGo search results may include ads/sponsored links.** `web_search` parses the result HTML from `html.duckduckgo.com/html` as-is and maintains no domain blocklist (neutrality principle — which queries and URLs to pick is entirely the agent's choice). The only safeguards are caps on size (`max_page_kb`, default 500KB) and time (`http_timeout_seconds`, default 20 seconds).
- Every URL the agent visits is recorded in the journal's `web_visits` field.
