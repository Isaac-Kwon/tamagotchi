"""Sandbox tests (M2): backend selection ladder + timeout (spec P3).

On Windows the effective backend is the plain-subprocess fallback; these tests
pin behaviour deterministically via monkeypatch and exercise the real
subprocess path (no isolation available in CI)."""

from __future__ import annotations

from soul.agent import sandbox


def test_select_backend_pinned():
    assert sandbox.select_backend("subprocess") == "subprocess"
    assert sandbox.select_backend("docker") == "docker"


def test_select_backend_auto_falls_back_to_subprocess(monkeypatch):
    # No linux tools, no docker -> plain subprocess (the honest fallback).
    monkeypatch.setattr(sandbox, "_has", lambda cmd: False)
    monkeypatch.setattr(sandbox, "_docker_available", lambda: False)
    assert sandbox.select_backend("auto") == sandbox.BACKEND_SUBPROCESS
    assert sandbox.backend_is_isolated(sandbox.BACKEND_SUBPROCESS) is False
    assert "NOT isolated" in sandbox.describe_backend(sandbox.BACKEND_SUBPROCESS)


def test_select_backend_auto_prefers_docker_when_available(monkeypatch):
    monkeypatch.setattr(sandbox, "_has", lambda cmd: False)  # no bwrap/unshare
    monkeypatch.setattr(sandbox, "_docker_available", lambda: True)
    assert sandbox.select_backend("auto") == sandbox.BACKEND_DOCKER
    assert sandbox.backend_is_isolated(sandbox.BACKEND_DOCKER) is True


def test_run_python_captures_stdout(tmp_path):
    res = sandbox.run_python(
        "print('hello sandbox')", work_dir=tmp_path / "sb", backend="subprocess"
    )
    assert res.backend == "subprocess"
    assert res.returncode == 0
    assert "hello sandbox" in res.stdout
    assert res.timed_out is False
    assert res.isolated is False


def test_run_python_times_out(tmp_path):
    res = sandbox.run_python(
        "import time\ntime.sleep(30)",
        work_dir=tmp_path / "sb",
        timeout_seconds=1,
        backend="subprocess",
    )
    assert res.timed_out is True
    assert res.returncode is None
    assert "timed out" in res.stderr


def test_run_python_nonzero_on_error(tmp_path):
    res = sandbox.run_python(
        "raise ValueError('boom')", work_dir=tmp_path / "sb", backend="subprocess"
    )
    assert res.returncode != 0
    assert "boom" in res.stderr


def test_files_written_by_snippet_persist_in_work_dir(tmp_path):
    """A file the snippet writes with a relative path survives the run — this is
    what lets the agent accumulate its own data in data/home/ across steps. Only
    the entry script (_experiment.py) is cleaned up."""
    work = tmp_path / "home"
    res = sandbox.run_python(
        "open('kept.txt', 'w').write('data')",
        work_dir=work,
        backend="subprocess",
    )
    assert res.returncode == 0
    assert (work / "kept.txt").read_text() == "data"
    # The scratch entry script is removed; the agent's artifact remains.
    assert not (work / "_experiment.py").exists()
