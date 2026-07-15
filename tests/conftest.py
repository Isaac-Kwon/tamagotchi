"""Shared pytest fixtures: a temporary, initialized data directory + config."""

from __future__ import annotations

import pytest

from soul.config import Config
from soul.paths import DataPaths, init_data_dir


@pytest.fixture
def data_paths(tmp_path) -> DataPaths:
    """An initialized data directory (tree + seeded SOUL.md + git repo) in tmp."""
    return init_data_dir(tmp_path / "data")


@pytest.fixture
def config(data_paths) -> Config:
    """A mock-mode config pointing at the temporary data directory."""
    cfg = Config()
    cfg.agent.data_dir = str(data_paths.root)
    cfg.llm.mock = True
    cfg.resolved_api_key = None
    return cfg
