"""Tests for config loading, validation, and API-key resolution (M0)."""

from __future__ import annotations

import json

import pytest

from soul.config import (
    Config,
    ConfigError,
    config_from_dict,
    load_config,
    resolve_api_key,
)


def _example_dict():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    return json.loads((root / "config.example.json").read_text(encoding="utf-8"))


def test_example_config_loads_and_validates():
    cfg = config_from_dict(_example_dict())
    assert cfg.llm.model == "gpt-4o-mini"
    assert cfg.agent.mode == "heartbeat"
    assert cfg.agent.heartbeat_minutes == 30
    assert cfg.report.timezone == "Asia/Seoul"


def test_unknown_top_level_section_rejected():
    raw = _example_dict()
    raw["bogus"] = {}
    with pytest.raises(ConfigError):
        config_from_dict(raw)


def test_unknown_key_in_section_rejected():
    raw = _example_dict()
    raw["llm"]["surprise"] = 1
    with pytest.raises(ConfigError):
        config_from_dict(raw)


def test_invalid_mode_rejected():
    raw = _example_dict()
    raw["agent"]["mode"] = "sideways"
    with pytest.raises(ConfigError):
        config_from_dict(raw)


def test_api_key_direct_wins(monkeypatch):
    cfg = Config()
    cfg.llm.api_key = "sk-direct"
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    resolve_api_key(cfg)
    assert cfg.resolved_api_key == "sk-direct"


def test_api_key_env_fallback(monkeypatch):
    cfg = Config()
    cfg.llm.api_key = None
    cfg.llm.api_key_env = "MY_KEY_VAR"
    monkeypatch.setenv("MY_KEY_VAR", "sk-from-env")
    resolve_api_key(cfg)
    assert cfg.resolved_api_key == "sk-from-env"


def test_api_key_missing_is_fine_for_local_llm(monkeypatch):
    # Local OpenAI-compatible endpoints (Ollama etc.) need no key: the client
    # omits the Authorization header when resolution yields None.
    cfg = Config()
    cfg.llm.api_key = None
    cfg.llm.api_key_env = "DEFINITELY_UNSET_VAR"
    monkeypatch.delenv("DEFINITELY_UNSET_VAR", raising=False)
    resolve_api_key(cfg)
    assert cfg.resolved_api_key is None
    assert cfg.llm.mock is False


def test_mock_override_needs_no_key(monkeypatch):
    cfg = Config()
    cfg.llm.api_key = None
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    resolve_api_key(cfg, mock_override=True)
    assert cfg.llm.mock is True
    assert cfg.resolved_api_key is None


def test_missing_config_file_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.json")


def test_load_config_from_file(tmp_path):
    raw = _example_dict()
    raw["llm"]["mock"] = True
    p = tmp_path / "config.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    cfg = load_config(p)
    assert cfg.llm.mock is True
    assert cfg.resolved_api_key is None
