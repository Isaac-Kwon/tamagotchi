"""Daily first-person retrospective report (spec P5, KOREAN by default).

Once a day, at ``report.time`` in ``report.timezone`` (``Asia/Seoul`` via
``zoneinfo``), the agent writes a first-person retrospective in the configured
``report.language`` (``ko``) to ``data/reports/YYYY-MM-DD.md``. Generation is:

    * **checked between steps** by the scheduler, in both heartbeat and
      continuous modes;
    * **idempotent** — keyed on the date file's existence, so a day is never
      reported twice;
    * **retried** — a failure leaves no file, so the next between-steps check
      tries again;
    * **committed** to the data git repo together with the day's journal (a
      once-a-day companion commit, spec P1).

The report's context includes the day's recent steps and the stated-vs-revealed
interest note, so the agent is shown the gap between what it said and what it did.
"""

from __future__ import annotations

import subprocess
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..config import Config
from ..paths import DataPaths
from ..storage import journal, state as state_store
from . import soul

# The report is written in the configured language (default Korean). The prompt
# is bilingual so the instruction is unambiguous while the OUTPUT stays Korean.
_REPORT_SYSTEM = """\
You are the same agent whose journal and self-description follow. Write a short \
first-person retrospective of your recent activity — what you found yourself \
drawn to, what you set aside, and how your stated interest compared with what \
your behaviour actually revealed. It is a private diary entry, not a report to \
anyone; be honest, including about contradictions between what you said and did.

Write the entire entry in {language_name} ({language_code}), in the first \
person. Output only the diary text (markdown is fine), with no preamble.
"""

_LANGUAGE_NAMES = {"ko": "Korean", "en": "English", "ja": "Japanese"}


def _tz(cfg: Config) -> ZoneInfo:
    return ZoneInfo(cfg.report.timezone)


def now_in_tz(cfg: Config) -> datetime:
    return datetime.now(_tz(cfg))


def report_date(cfg: Config, now: datetime | None = None) -> str:
    """The YYYY-MM-DD date (in the report timezone) a report would cover."""
    now = now or now_in_tz(cfg)
    return now.strftime("%Y-%m-%d")


def report_path(cfg: Config, paths: DataPaths, date_str: str | None = None):
    date_str = date_str or report_date(cfg)
    return paths.reports_dir / f"{date_str}.md"


def _parse_time(hhmm: str) -> tuple[int, int]:
    try:
        h, m = hhmm.split(":", 1)
        return max(0, min(23, int(h))), max(0, min(59, int(m)))
    except (ValueError, AttributeError):
        return 22, 0


def is_due(cfg: Config, paths: DataPaths, now: datetime | None = None) -> bool:
    """True when today's report should exist but does not yet (spec P5).

    Due once the local time has reached ``report.time`` for the current date and
    no ``reports/YYYY-MM-DD.md`` exists for it.
    """
    now = now or now_in_tz(cfg)
    hour, minute = _parse_time(cfg.report.time)
    trigger = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now < trigger:
        return False
    return not report_path(cfg, paths, report_date(cfg, now)).exists()


def build_report_messages(
    cfg: Config, soul_text: str, recent_steps: list[dict[str, Any]], revealed_note: str | None
) -> list[dict[str, Any]]:
    """Assemble the report call: system instruction + a context user message."""
    lang = cfg.report.language
    system = _REPORT_SYSTEM.format(
        language_name=_LANGUAGE_NAMES.get(lang, lang), language_code=lang
    )

    lines: list[str] = ["Your self-description (SOUL.md):", soul_text.strip(), ""]
    if recent_steps:
        lines.append("Recent steps (oldest first):")
        for s in recent_steps:
            summ = s.get("summary") or s.get("topic") or "(no summary)"
            dec = s.get("decision")
            interest = s.get("interest")
            tag = f" [interest {interest}, {dec}]" if dec else ""
            lines.append(f"- {s.get('id', '?')}: {summ}{tag}")
    else:
        lines.append("Recent steps: none yet.")
    lines.append("")
    if revealed_note:
        lines.append("Stated vs revealed interest (behavioural signal):")
        lines.append(revealed_note)

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(lines)},
    ]


def _git(paths: DataPaths, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(paths.root), *args],
        capture_output=True, text=True, check=False,
    )


def _commit_report(paths: DataPaths, date_str: str) -> str | None:
    """Commit the report with the day's journal + notes (companion commit, P1)."""
    _git(paths, "add", "reports", "journal", "notes")
    commit = _git(paths, "commit", "-q", "-m", f"report: {date_str}")
    if commit.returncode != 0:
        commit = _git(paths, "commit", "-q", "-m", f"report: {date_str}")
        if commit.returncode != 0:
            return None
    head = _git(paths, "rev-parse", "HEAD")
    return head.stdout.strip() or None if head.returncode == 0 else None


def generate_report(
    cfg: Config, paths: DataPaths, llm: Any, now: datetime | None = None
) -> dict[str, Any] | None:
    """Generate, write, journal, and commit today's report. Returns the record.

    Returns None if the LLM call fails (no file is written, so a later check
    retries — spec P5). Raises nothing to the caller.
    """
    now = now or now_in_tz(cfg)
    date_str = report_date(cfg, now)
    path = report_path(cfg, paths, date_str)
    if path.exists():
        return None  # idempotent

    soul_text = soul.read_soul(paths)
    recent = journal.tail(paths, cfg.agent.context_recent_steps)
    try:
        revealed = journal.revealed_interest(journal.read_all(paths))
        revealed_note = revealed.get("stated_vs_revealed_note")
    except Exception:  # noqa: BLE001
        revealed_note = None

    messages = build_report_messages(cfg, soul_text, recent, revealed_note)
    try:
        resp = llm.chat(messages)
    except Exception:  # noqa: BLE001 — a failed report must not crash the loop.
        return None

    content = (resp.content or "").strip()
    if not content:
        return None

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content + "\n", encoding="utf-8")

    # Journal a report record, then commit report + journal together.
    step_id, st = state_store.next_step_id(paths.state_json)
    record = journal.new_step_record(
        step_id,
        kind="report",
        topic=f"daily report {date_str}",
        summary=f"Wrote the daily retrospective for {date_str}.",
        content_path=f"reports/{date_str}.md",
    )
    journal.append_step(paths, record)

    commit = _commit_report(paths, date_str)
    record["soul_commit"] = commit

    st["today_report"] = {"date": date_str, "path": f"reports/{date_str}.md"}
    state_store.write_state(paths.state_json, st)
    return record


def check_report(
    cfg: Config, paths: DataPaths, llm: Any, now: datetime | None = None
) -> dict[str, Any] | None:
    """Generate the report if due (idempotent). Called between steps (spec P5)."""
    if not is_due(cfg, paths, now):
        return None
    return generate_report(cfg, paths, llm, now)
