"""Entry point for the agent loop.

Milestone M1 supports a single wake step under mock or a real key:

    python run_agent.py --once --mock     # one step with the FakeLLM
    python run_agent.py --once            # one step with the real LLM

The continuous / heartbeat scheduler arrives in M5.
"""

from __future__ import annotations

import argparse
import sys

from soul.agent import loop
from soul.agent.fake_llm import FakeLLM
from soul.agent.lock import AgentLock, LockError
from soul.agent.llm import LLMClient
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

    if not args.once:
        print(
            "Only --once is supported in this milestone (M1). "
            "The scheduler arrives in M5.",
            file=sys.stderr,
        )
        return 2

    try:
        with AgentLock(paths.agent_lock):
            record = loop.run_step(cfg, paths, llm)
    except LockError as exc:
        print(f"Another agent instance is running: {exc}", file=sys.stderr)
        return 3

    print(f"Step {record['id']} done: kind={record['kind']} "
          f"action={record.get('action')} decision={record.get('decision')}")
    if record.get("soul_updated"):
        print(f"  SOUL.md updated -> commit {record.get('soul_commit')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
