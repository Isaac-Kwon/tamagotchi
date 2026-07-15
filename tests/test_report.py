"""Tests for the daily Korean retrospective report (M5, spec P5)."""

from __future__ import annotations

import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

from soul.agent import report
from soul.agent.fake_llm import FakeLLM
from soul.storage import journal, state as state_store

KOREAN = "오늘 나는 여러 가지를 시도했고, 그 중 몇 가지에 끌렸다. 스스로에게 정직하려 한다."


def _seed_step(data_paths):
    rec = journal.new_step_record(
        "step-000001", kind="wake_step", action="free_write", topic="a thing",
        interest=7, decision="deepen", summary="wrote about a thing", thread_id="th-0001",
    )
    journal.append_step(data_paths, rec)


def test_is_due_before_and_after_time(config, data_paths):
    tz = ZoneInfo(config.report.timezone)
    before = datetime(2026, 7, 15, 21, 59, tzinfo=tz)
    after = datetime(2026, 7, 15, 22, 30, tzinfo=tz)
    assert report.is_due(config, data_paths, before) is False
    assert report.is_due(config, data_paths, after) is True


def test_generate_report_korean_committed_and_idempotent(config, data_paths):
    _seed_step(data_paths)
    tz = ZoneInfo(config.report.timezone)
    now = datetime(2026, 7, 15, 22, 30, tzinfo=tz)

    llm = FakeLLM([KOREAN])
    rec = report.generate_report(config, data_paths, llm, now)
    assert rec is not None
    assert rec["kind"] == "report"

    path = data_paths.reports_dir / "2026-07-15.md"
    assert path.exists()
    assert "정직" in path.read_text(encoding="utf-8")

    # A report record is journaled.
    reports = [s for s in journal.read_all(data_paths) if s.get("kind") == "report"]
    assert len(reports) == 1

    # The report was committed to the data git repo (companion commit, P1).
    log = subprocess.run(
        ["git", "-C", str(data_paths.root), "log", "--oneline"],
        capture_output=True, text=True,
    )
    assert "report: 2026-07-15" in log.stdout

    # state.json today_report updated.
    st = state_store.read_state(data_paths.state_json)
    assert st["today_report"]["date"] == "2026-07-15"

    # Idempotent: a second call does nothing (no LLM call, no new file write).
    llm2 = FakeLLM([KOREAN])
    assert report.generate_report(config, data_paths, llm2, now) is None
    assert len(llm2.calls) == 0


def test_check_report_generates_when_due(config, data_paths):
    tz = ZoneInfo(config.report.timezone)
    now = datetime(2026, 7, 15, 23, 0, tzinfo=tz)
    llm = FakeLLM([KOREAN])
    rec = report.check_report(config, data_paths, llm, now)
    assert rec is not None
    assert (data_paths.reports_dir / "2026-07-15.md").exists()


def test_report_failure_leaves_no_file_for_retry(config, data_paths):
    """A failed LLM report writes no file, so a later check retries (spec P5)."""
    from soul.agent.llm import LLMError

    tz = ZoneInfo(config.report.timezone)
    now = datetime(2026, 7, 15, 22, 30, tzinfo=tz)
    llm = FakeLLM([LLMError("down")])
    assert report.generate_report(config, data_paths, llm, now) is None
    assert not (data_paths.reports_dir / "2026-07-15.md").exists()
    assert report.is_due(config, data_paths, now) is True
