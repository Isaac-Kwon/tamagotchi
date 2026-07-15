"""Entry point for the agent loop.

    python run_agent.py                   # long-running scheduler (default, M5)
    python run_agent.py --once            # a single wake step, then exit
    python run_agent.py --once --mock     # one step with the FakeLLM
    python run_agent.py --mock            # long-running scheduler under the FakeLLM

The default is the long-running scheduler (heartbeat or continuous per config),
which also emits the daily report and enforces chat preemption. The
``agent.lock`` is held for the whole process lifetime so a second instance is
refused (spec P5). ``scripts/start_agent.ps1`` wraps this with auto-restart.
"""

from __future__ import annotations

import argparse
import sys

from soul.agent import loop, scheduler
from soul.agent.fake_llm import FakeLLM
from soul.agent.llm import LLMClient
from soul.agent.lock import AgentLock, LockError
from soul.config import ConfigError, load_config
from soul.paths import init_data_dir


def _make_llm(cfg):
    """Return a chat client: FakeLLM when mocking, else the real LLMClient."""
    if cfg.llm.mock:
        return FakeLLM()
    return LLMClient(
        base_url=cfg.llm.base_url,
        model=cfg.llm.model,
        api_key=cfg.resolved_api_key,
        timeout_seconds=cfg.llm.timeout_seconds,
        max_retries=cfg.llm.max_retries,
        temperature=cfg.llm.temperature,
        max_output_tokens=cfg.llm.max_output_tokens,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Soul Tamagotchi agent loop.")
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    parser.add_argument("--once", action="store_true", help="Run a single wake step and exit")
    parser.add_argument("--mock", action="store_true", help="Use the FakeLLM (no API key needed)")
    args = parser.parse_args(argv)

    try:
        cfg = load_config(args.config, mock_override=args.mock)
    except ConfigError as exc:
        print(f"Configuration error:\n{exc}", file=sys.stderr)
        return 2

    paths = init_data_dir(cfg.agent.data_dir)
    llm = _make_llm(cfg)

    try:
        with AgentLock(paths.agent_lock):
            if args.once:
                record = loop.run_step(cfg, paths, llm)
                print(
                    f"Step {record['id']} done: kind={record['kind']} "
                    f"action={record.get('action')} decision={record.get('decision')}"
                )
                if record.get("soul_updated"):
                    print(f"  SOUL.md updated -> commit {record.get('soul_commit')}")
                return 0

            # Long-running scheduler (default). Blocks until interrupted.
            print(
                f"Agent scheduler starting (mode={cfg.agent.mode}, "
                f"heartbeat={cfg.agent.heartbeat_minutes}m). Ctrl-C to stop."
            )
            try:
                scheduler.run_scheduler(cfg, paths, llm)
            except KeyboardInterrupt:
                print("Scheduler stopped.")
            return 0
    except LockError as exc:
        print(f"Another agent instance is running: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
