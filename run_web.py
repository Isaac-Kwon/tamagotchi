"""Entry point for the API server (spec P1/P5, M6).

    python run_web.py                 # serve on config web.host:web.port
    python run_web.py --mock          # answer chats with the FakeLLM (no key)

Runs uvicorn on the FastAPI app. This is a separate process from the agent loop;
they share only the data directory. ``scripts/start_web.ps1`` wraps this with
auto-restart.
"""

from __future__ import annotations

import argparse
import sys

import uvicorn

from soul.config import ConfigError, load_config
from soul.paths import init_data_dir
from soul.web.server import create_app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Soul Tamagotchi API server.")
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    parser.add_argument("--mock", action="store_true", help="Use the FakeLLM for chat")
    args = parser.parse_args(argv)

    try:
        cfg = load_config(args.config, mock_override=args.mock)
    except ConfigError as exc:
        print(f"Configuration error:\n{exc}", file=sys.stderr)
        return 2

    paths = init_data_dir(cfg.agent.data_dir)
    app = create_app(cfg, paths)

    uvicorn.run(app, host=cfg.web.host, port=cfg.web.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
