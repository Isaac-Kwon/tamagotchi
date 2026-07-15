"""Out-of-process execution of self-authored skills (spec P8).

Skill code is **never imported into the agent process**. Instead it runs in a
separate subprocess through the P3 sandbox ladder (:mod:`soul.agent.sandbox`):

    * the skill's ``params`` dict is handed in as JSON on stdin,
    * a tiny harness ``exec``\\ s ``skill.py`` (its own stdout suppressed) and
      calls ``run(params)``,
    * the returned dict is emitted as JSON on stdout.

Any failure — a non-stdlib import caught by the static check, a timeout, an
exception/crash, or non-JSON / malformed output — becomes an ordinary "skill
failed" result. The wake loop treats that as normal step content; the loop is
never killed and the skill's failure counter is advanced by the caller.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from ..config import Config
from ..paths import DataPaths
from . import sandbox, skills

logger = logging.getLogger("soul.skill_runner")

# The harness executed inside the sandbox. It loads skill.py from the (bound)
# working directory, suppresses the skill's own stdout so only the result JSON
# lands on real stdout, and prints ``run(params)`` as JSON.
_HARNESS = r'''
import contextlib, io, json, sys

def _main():
    params = json.loads(sys.stdin.read() or "{}")
    with open("skill.py", "r", encoding="utf-8") as fh:
        src = fh.read()
    ns = {"__name__": "__skill__"}
    exec(compile(src, "skill.py", "exec"), ns)
    run = ns.get("run")
    if not callable(run):
        raise SystemExit("skill defines no run()")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = run(params)
    sys.stdout.write(json.dumps(result, ensure_ascii=False, default=str))

_main()
'''


@dataclass
class SkillRunResult:
    """Outcome of running one skill."""

    name: str
    ok: bool
    output: str            # markdown — the skill output, or a failure message
    backend: str | None    # sandbox backend used (None when not run)
    isolated: bool         # honest isolation flag (False for subprocess fallback)
    error: str | None = None


def _fail(name: str, reason: str, backend: str | None = None,
          isolated: bool = False, detail: str = "") -> SkillRunResult:
    body = (
        f"# skill:{name} failed\n\n"
        f"The skill did not complete successfully.\n\n"
        f"Reason: {reason}."
    )
    if backend is not None:
        body += f"\n\n(sandbox backend: `{backend}`" \
                f"{', not isolated' if not isolated else ''})"
    if detail.strip():
        body += f"\n\n```\n{detail.strip()}\n```"
    return SkillRunResult(name=name, ok=False, output=body, backend=backend,
                          isolated=isolated, error=reason)


def run_skill(
    cfg: Config, paths: DataPaths, name: str, params: dict[str, Any]
) -> SkillRunResult:
    """Run skill ``name`` with ``params`` in an isolated subprocess.

    Returns a :class:`SkillRunResult`; never raises for a skill-level problem.
    The static stdlib-only import check is re-run here (spec P8: before every
    run), so a skill that was edited on disk to import a third-party module is
    rejected without executing.
    """
    manifest = skills.read_manifest(paths, name)
    if manifest is None:
        return _fail(name, "skill is not registered")

    entry = skills.entry_path(paths, name)
    if not entry.exists():
        return _fail(name, "skill has no skill.py entry file")
    code = entry.read_text(encoding="utf-8")

    # Re-check imports before every run (spec P8).
    ok, message = skills.check_imports(code)
    if not ok:
        return _fail(name, message)

    # Dedicated per-skill work dir inside data/sandbox; copy skill.py alongside
    # the harness so the harness can load it by relative path.
    work = paths.sandbox_dir / "skills" / name
    work.mkdir(parents=True, exist_ok=True)
    (work / "skill.py").write_text(code, encoding="utf-8")

    result = sandbox.run_python(
        _HARNESS,
        work_dir=work,
        timeout_seconds=cfg.skills.timeout_seconds,
        backend=cfg.sandbox.backend,
        stdin=json.dumps(params, ensure_ascii=False),
    )
    # Surface the isolation reality in the log (spec P8 honesty line).
    logger.info(
        "skill %s ran via %s (%s)",
        name, result.backend,
        "isolated" if result.isolated else "NOT isolated",
    )

    if result.timed_out:
        return _fail(name, f"timed out after {cfg.skills.timeout_seconds}s",
                     result.backend, result.isolated, result.stderr)
    if result.returncode != 0:
        return _fail(name, "the skill raised an exception",
                     result.backend, result.isolated, result.stderr)

    out = (result.stdout or "").strip()
    try:
        payload = json.loads(out)
    except json.JSONDecodeError:
        return _fail(name, "the skill did not return valid JSON",
                     result.backend, result.isolated, out[:500])
    if not isinstance(payload, dict) or "output" not in payload:
        return _fail(name, "the skill result had no 'output' field",
                     result.backend, result.isolated, out[:500])

    return SkillRunResult(
        name=name, ok=True, output=str(payload["output"]),
        backend=result.backend, isolated=result.isolated,
    )
