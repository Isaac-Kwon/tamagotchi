"""Self-authored skill registry (spec P8).

The agent can extend its own action space by writing *skills*. A skill lives in
``data/skills/<name>/`` as:

    * ``manifest.json`` — ``{"name", "description", "entry": "skill.py",
      "version", "enabled", "failures", "created_at"}`` (plus a transient
      ``notice_pending`` flag used to surface an auto-disable notice once).
    * ``skill.py`` — a module defining ``def run(params: dict) -> dict`` that
      returns ``{"output": "<markdown>"}``.

Built-in skills are the source-repo ``actions.py`` / ``webtools.py`` and cannot
be changed (the agent only writes to the data directory). Self-authored skills
are version-controlled in the *data* git repo — their creation and edits are
part of the soul's growth history, so this module commits them following the
``soul.py`` / ``wiki.py`` pattern.

This module never imports or executes skill code. Static safety checks (a
``run`` function must exist; only standard-library imports are allowed) run both
here at registration time and again in :mod:`soul.agent.skill_runner` before
every execution. Execution itself happens out-of-process via the sandbox ladder.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

from ..paths import DataPaths

ENTRY = "skill.py"
MANIFEST = "manifest.json"

# A skill name is a slug: lowercase, starts alphanumeric, then alnum/-/_ .
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_MAX_NAME_LEN = 64

# Modules always permitted even if not reported by sys.stdlib_module_names.
_ALWAYS_ALLOWED = frozenset({"__future__"})


class SkillError(Exception):
    """Raised when a skill fails validation at registration (user-facing message)."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Static validation (name, run(), stdlib-only imports)
# --------------------------------------------------------------------------- #
def valid_skill_name(name: Any) -> bool:
    """True when ``name`` is a safe slug usable as a directory name."""
    return (
        isinstance(name, str)
        and 0 < len(name) <= _MAX_NAME_LEN
        and bool(_NAME_RE.match(name))
    )


def _imported_roots(tree: ast.AST) -> list[tuple[str, int]]:
    """Return ``(root_module, lineno)`` for every import in ``tree``.

    A relative import (``from . import x``) has a root of ``""`` — reported so it
    can be rejected: a standalone skill must not reach into sibling modules.
    """
    roots: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.append((alias.name.split(".")[0], node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                roots.append(("", node.lineno))  # relative import — reject
            elif node.module:
                roots.append((node.module.split(".")[0], node.lineno))
    return roots


def check_imports(code: str) -> tuple[bool, str]:
    """Static scan: reject any import that is not standard-library.

    Returns ``(ok, message)``. Run at registration AND before every execution
    (spec P8). Parses the source; a syntax error is itself a rejection.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return False, f"skill has a syntax error: {exc}"

    allowed = set(sys.stdlib_module_names) | _ALWAYS_ALLOWED
    for root, lineno in _imported_roots(tree):
        if root == "":
            return False, f"relative imports are not allowed (line {lineno})."
        if root not in allowed:
            return (
                False,
                f"import of non-standard-library module '{root}' is not allowed "
                f"(line {lineno}); skills may use the Python standard library only.",
            )
    return True, ""


def has_run(code: str) -> bool:
    """True when ``code`` defines a top-level ``run`` function taking >=1 arg."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run":
            args = node.args
            if len(args.args) + len(args.posonlyargs) >= 1 or args.vararg is not None:
                return True
    return False


def validate_skill_code(code: str) -> None:
    """Raise :class:`SkillError` if ``code`` is not a registrable skill."""
    if not has_run(code):
        raise SkillError(
            "skill code must define `def run(params: dict) -> dict` at the top level."
        )
    ok, message = check_imports(code)
    if not ok:
        raise SkillError(message)


# --------------------------------------------------------------------------- #
# Paths + manifest IO
# --------------------------------------------------------------------------- #
def skill_dir(paths: DataPaths, name: str):
    return paths.skills_dir / name


def manifest_path(paths: DataPaths, name: str):
    return skill_dir(paths, name) / MANIFEST


def entry_path(paths: DataPaths, name: str):
    return skill_dir(paths, name) / ENTRY


def read_manifest(paths: DataPaths, name: str) -> dict[str, Any] | None:
    """Return a skill's manifest dict, or ``None`` if missing/unreadable."""
    path = manifest_path(paths, name)
    if not path.exists():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return obj if isinstance(obj, dict) else None


def _write_manifest(paths: DataPaths, name: str, manifest: dict[str, Any]) -> None:
    path = manifest_path(paths, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def list_skills(paths: DataPaths) -> list[dict[str, Any]]:
    """All registered skills' manifests (sorted by name)."""
    out: list[dict[str, Any]] = []
    if not paths.skills_dir.exists():
        return out
    for child in sorted(paths.skills_dir.iterdir()):
        if not child.is_dir():
            continue
        m = read_manifest(paths, child.name)
        if m is not None:
            m.setdefault("name", child.name)
            out.append(m)
    return out


def list_enabled(paths: DataPaths) -> list[str]:
    """Names of skills that are enabled AND have a runnable entry file."""
    names: list[str] = []
    for m in list_skills(paths):
        name = m.get("name")
        if m.get("enabled") is True and name and entry_path(paths, name).exists():
            names.append(str(name))
    return names


# --------------------------------------------------------------------------- #
# Git commit of skill files (follows the soul.py / wiki.py pattern)
# --------------------------------------------------------------------------- #
def _git(paths: DataPaths, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(paths.root), *args],
        capture_output=True, text=True, check=False,
    )


def _commit_skill(paths: DataPaths, name: str, message: str) -> str | None:
    """Stage and commit ``skills/<name>/``. Returns the commit hash or None."""
    _git(paths, "add", f"skills/{name}")
    commit = _git(paths, "commit", "-q", "-m", message)
    if commit.returncode != 0:
        commit = _git(paths, "commit", "-q", "-m", message)  # retry once (spec P5)
        if commit.returncode != 0:
            return None
    head = _git(paths, "rev-parse", "HEAD")
    return (head.stdout.strip() or None) if head.returncode == 0 else None


# --------------------------------------------------------------------------- #
# Registration + failure lifecycle
# --------------------------------------------------------------------------- #
def create_skill(
    paths: DataPaths, name: str, description: str, code: str
) -> dict[str, Any]:
    """Validate and register a new skill, committing it to the data repo.

    Raises :class:`SkillError` with a user-facing message on any validation
    failure (bad name, missing ``run``, non-stdlib import). Returns the manifest.
    """
    if not valid_skill_name(name):
        raise SkillError(
            f"invalid skill name {name!r}: use lowercase letters, digits, "
            "'-' or '_' (must start with a letter or digit)."
        )
    validate_skill_code(code)

    existing = read_manifest(paths, name)
    created_at = existing.get("created_at") if existing else None
    manifest = {
        "name": name,
        "description": str(description or "").strip(),
        "entry": ENTRY,
        "version": (int(existing.get("version", 1)) + 1) if existing else 1,
        "enabled": True,
        "failures": 0,
        "created_at": created_at or _now_iso(),
        "updated_at": _now_iso(),
        "notice_pending": False,
    }

    entry_path(paths, name).parent.mkdir(parents=True, exist_ok=True)
    entry_path(paths, name).write_text(code, encoding="utf-8")
    _write_manifest(paths, name, manifest)

    verb = "update" if existing else "create"
    commit = _commit_skill(paths, name, f"skill: {verb} {name}")
    manifest["commit"] = commit
    return manifest


def record_success(paths: DataPaths, name: str) -> None:
    """Reset the consecutive-failure counter after a clean run (spec P8)."""
    m = read_manifest(paths, name)
    if m is None:
        return
    if int(m.get("failures", 0) or 0) != 0:
        m["failures"] = 0
        _write_manifest(paths, name, m)


def record_failure(
    paths: DataPaths, name: str, *, auto_disable_after: int
) -> dict[str, Any]:
    """Increment a skill's failure count; auto-disable at the threshold (spec P8).

    Returns ``{"failures", "enabled", "auto_disabled"}``. When the threshold is
    reached the skill is disabled and a one-time notice is queued (surfaced in
    the next step's context via :func:`drain_notices`) so the agent can fix or
    abandon it. The manifest change is committed only on the auto-disable
    transition (a meaningful lifecycle event), keeping git history readable.
    """
    m = read_manifest(paths, name)
    if m is None:
        return {"failures": 0, "enabled": False, "auto_disabled": False}

    failures = int(m.get("failures", 0) or 0) + 1
    m["failures"] = failures
    m["updated_at"] = _now_iso()
    auto_disabled = False
    if m.get("enabled") is True and failures >= auto_disable_after:
        m["enabled"] = False
        m["notice_pending"] = True
        auto_disabled = True

    _write_manifest(paths, name, m)
    if auto_disabled:
        _commit_skill(paths, name, f"skill: auto-disable {name} after {failures} failures")
    return {"failures": failures, "enabled": bool(m.get("enabled")),
            "auto_disabled": auto_disabled}


def drain_notices(paths: DataPaths) -> list[str]:
    """Return + clear one-time notices about auto-disabled skills (spec P8).

    A skill auto-disabled last step carries ``notice_pending``; this collects a
    neutral notice for each and clears the flag so it surfaces exactly once in
    the next context. Mirrors the inbox drain pattern.
    """
    notices: list[str] = []
    for m in list_skills(paths):
        if m.get("notice_pending") is True:
            name = m.get("name")
            notices.append(
                f'The skill "{name}" was turned off automatically after '
                f'{m.get("failures", "several")} failures. You can rewrite it with '
                "skill_write or leave it be."
            )
            m["notice_pending"] = False
            if name:
                _write_manifest(paths, str(name), m)
    return notices
