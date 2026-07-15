"""FastAPI application factory (spec P1/P5, M6).

Assembles the REST/SSE router and mounts the static web client at ``/``. The UI
is a separate concern (M7, built in parallel) — this factory only ensures a
placeholder ``index.html`` exists when the static dir is otherwise empty, and
never writes other static files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ..config import Config
from ..paths import DataPaths, init_data_dir
from .api import build_router
from .chat import ChatManager

STATIC_DIR = Path(__file__).resolve().parent / "static"

_PLACEHOLDER_INDEX = """\
<!doctype html>
<meta charset="utf-8">
<title>Soul Tamagotchi</title>
<h1>Soul Tamagotchi API</h1>
<p>This is a placeholder. The web UI is served from this directory once built.</p>
<p>The API is live under <code>/api</code> — e.g.
<a href="/api/state">/api/state</a>.</p>
"""


def _ensure_placeholder_index() -> None:
    """Create a placeholder index.html only if the static dir has no files."""
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    has_files = any(p.is_file() for p in STATIC_DIR.iterdir())
    if not has_files:
        (STATIC_DIR / "index.html").write_text(_PLACEHOLDER_INDEX, encoding="utf-8")


def _make_llm(cfg: Config) -> Any:
    if cfg.llm.mock:
        from ..agent.fake_llm import FakeLLM
        return FakeLLM()
    from ..agent.llm import LLMClient
    return LLMClient(
        base_url=cfg.llm.base_url,
        model=cfg.llm.model,
        api_key=cfg.resolved_api_key,
        timeout_seconds=cfg.llm.timeout_seconds,
        max_retries=cfg.llm.max_retries,
        temperature=cfg.llm.temperature,
        max_output_tokens=cfg.llm.max_output_tokens,
    )


def create_app(
    cfg: Config,
    paths: DataPaths | None = None,
    *,
    llm: Any | None = None,
) -> FastAPI:
    """Build the FastAPI app. ``paths``/``llm`` are injectable for tests."""
    if paths is None:
        paths = init_data_dir(cfg.agent.data_dir)
    if llm is None:
        llm = _make_llm(cfg)

    chat_manager = ChatManager(paths, cfg, llm)

    app = FastAPI(title="Soul Tamagotchi API")
    app.state.cfg = cfg
    app.state.paths = paths
    app.state.chat_manager = chat_manager

    # API routes first so they win over the catch-all static mount.
    app.include_router(build_router(cfg, paths, chat_manager))

    _ensure_placeholder_index()
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

    return app
