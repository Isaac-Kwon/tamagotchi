"""Self-authored skill system tests (M8, spec P8).

Covers the full lifecycle with FakeLLM + fixture skills:
  * skill_write -> files on disk + manifest + data-repo commit + next action list
  * execution success (echoing params), timeout, crash, non-JSON stdout
  * 3 consecutive failures -> enabled:false + notice surfaced in next context
  * non-stdlib import rejected at write AND at run
  * disabled skills are not listed

The subprocess backend is pinned everywhere skills run, for determinism.
"""

from __future__ import annotations

import json
import subprocess

from soul.agent import actions as actions_mod
from soul.agent import loop, skill_runner, skills
from soul.agent.fake_llm import FakeLLM
from soul.agent.llm import LLMResponse
from soul.knowledge import tools as ktools


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _tool_call(name, args, call_id="c1"):
    return {"id": call_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


def _tool_response(*calls):
    raw = {"choices": [{"message": {"content": "", "tool_calls": list(calls)}}]}
    return LLMResponse(content="", raw=raw, model="fake", tool_calls=list(calls))


def _act(action="free_write", topic="t", content="# n\n\nbody"):
    return {"action": action, "topic": topic, "content": content}


def _reflect(**over):
    base = {"interest": 6, "interest_delta": "first", "mood": "curious",
            "reason": "r", "decision": "new", "summary": "s",
            "soul_update": {"update": False, "content": "", "reason": ""}}
    base.update(over)
    return base


def _last_commit_subject(paths) -> str:
    out = subprocess.run(["git", "-C", str(paths.root), "log", "--format=%s", "-1"],
                         capture_output=True, text=True, check=False)
    return out.stdout.strip()


def _all_commit_subjects(paths) -> list[str]:
    out = subprocess.run(["git", "-C", str(paths.root), "log", "--format=%s"],
                         capture_output=True, text=True, check=False)
    return out.stdout.splitlines()


ECHO_SKILL = (
    "def run(params):\n"
    "    return {'output': '# Echo\\n\\ntopic=' + str(params.get('topic'))}\n"
)
CRASH_SKILL = "def run(params):\n    raise ValueError('boom')\n"
SLEEP_SKILL = "import time\ndef run(params):\n    time.sleep(10)\n    return {'output': 'done'}\n"
# Scribbles directly on fd 1 (bypassing the harness stdout suppression) so the
# real stdout is not valid JSON.
BADJSON_SKILL = (
    "import os\n"
    "def run(params):\n"
    "    os.write(1, b'not json at all')\n"
    "    return {'output': 'x'}\n"
)
NONSTDLIB_SKILL = "import numpy\ndef run(params):\n    return {'output': 'x'}\n"


def _install_skill_directly(paths, name, code, *, enabled=True):
    """Write a skill's files straight to disk, bypassing create_skill validation."""
    d = skills.skill_dir(paths, name)
    d.mkdir(parents=True, exist_ok=True)
    skills.entry_path(paths, name).write_text(code, encoding="utf-8")
    manifest = {"name": name, "description": "d", "entry": "skill.py", "version": 1,
                "enabled": enabled, "failures": 0, "created_at": "2026-01-01T00:00:00+00:00",
                "notice_pending": False}
    skills.manifest_path(paths, name).write_text(json.dumps(manifest), encoding="utf-8")


def _run_skill_step(config, data_paths, skill_name, topic="hi"):
    llm = FakeLLM([_act(action=f"skill:{skill_name}", topic=topic), _reflect()])
    return loop.run_step(config, data_paths, llm)


# --------------------------------------------------------------------------- #
# 1. skill_write: files + manifest + commit + next action list
# --------------------------------------------------------------------------- #
def test_skill_write_creates_files_manifest_commit_and_action(config, data_paths):
    llm = FakeLLM([
        _tool_response(_tool_call("skill_write", {
            "name": "greet", "description": "say hi", "code": ECHO_SKILL})),
        _act(),        # tool-less final ACT
        _reflect(),
    ])
    loop.run_step(config, data_paths, llm)

    # Files on disk.
    assert skills.entry_path(data_paths, "greet").exists()
    manifest = skills.read_manifest(data_paths, "greet")
    assert manifest["name"] == "greet"
    assert manifest["entry"] == "skill.py"
    assert manifest["enabled"] is True
    assert manifest["failures"] == 0
    assert manifest["created_at"]

    # Committed to the data repo.
    assert "skill: create greet" in _all_commit_subjects(data_paths)

    # Appears in the NEXT step's action list, neutrally.
    assert skills.list_enabled(data_paths) == ["greet"]
    names = [a["name"] for a in actions_mod.available_actions(skills=["greet"])]
    assert "skill:greet" in names

    # And really shows up in the following step's ACT prompt.
    llm2 = FakeLLM([_act(), _reflect()])
    loop.run_step(config, data_paths, llm2)
    prompt = json.dumps(llm2.calls[0]["messages"], ensure_ascii=False)
    assert "skill:greet" in prompt


# --------------------------------------------------------------------------- #
# 2. successful execution echoes params, journals skill_used + backend
# --------------------------------------------------------------------------- #
def test_skill_execution_success(config, data_paths):
    config.sandbox.backend = "subprocess"
    skills.create_skill(data_paths, "greet", "say hi", ECHO_SKILL)

    record = _run_skill_step(config, data_paths, "greet", topic="weather")
    assert record["kind"] == "wake_step"
    assert record["action"] == "skill:greet"
    assert record["skill_used"] == "greet"
    assert record["sandbox_backend"] == "subprocess"

    note = (data_paths.notes_dir / f"{record['id']}.md").read_text(encoding="utf-8")
    assert "topic=weather" in note

    # A clean run leaves the failure counter at 0.
    assert skills.read_manifest(data_paths, "greet")["failures"] == 0


# --------------------------------------------------------------------------- #
# 3-5. timeout / crash / non-JSON all fail gracefully; the loop survives
# --------------------------------------------------------------------------- #
def test_skill_timeout_fails_but_loop_survives(config, data_paths):
    config.sandbox.backend = "subprocess"
    config.skills.timeout_seconds = 1
    skills.create_skill(data_paths, "slow", "slow", SLEEP_SKILL)

    record = _run_skill_step(config, data_paths, "slow")
    assert record["kind"] == "wake_step"          # loop did NOT die
    note = (data_paths.notes_dir / f"{record['id']}.md").read_text(encoding="utf-8")
    assert "failed" in note and "timed out" in note
    assert skills.read_manifest(data_paths, "slow")["failures"] == 1


def test_skill_crash_fails_but_loop_survives(config, data_paths):
    config.sandbox.backend = "subprocess"
    skills.create_skill(data_paths, "crash", "boom", CRASH_SKILL)

    record = _run_skill_step(config, data_paths, "crash")
    assert record["kind"] == "wake_step"
    note = (data_paths.notes_dir / f"{record['id']}.md").read_text(encoding="utf-8")
    assert "failed" in note
    assert skills.read_manifest(data_paths, "crash")["failures"] == 1


def test_skill_non_json_output_fails(config, data_paths):
    config.sandbox.backend = "subprocess"
    skills.create_skill(data_paths, "bad", "bad", BADJSON_SKILL)

    record = _run_skill_step(config, data_paths, "bad")
    assert record["kind"] == "wake_step"
    result = skill_runner.run_skill(config, data_paths, "bad", {"topic": "x"})
    assert result.ok is False
    assert "JSON" in result.error


# --------------------------------------------------------------------------- #
# 6. three consecutive failures -> disabled + notice in next context
# --------------------------------------------------------------------------- #
def test_three_failures_auto_disable_and_notice(config, data_paths):
    config.sandbox.backend = "subprocess"
    config.skills.auto_disable_after_failures = 3
    skills.create_skill(data_paths, "crash", "boom", CRASH_SKILL)

    for _ in range(3):
        _run_skill_step(config, data_paths, "crash")

    manifest = skills.read_manifest(data_paths, "crash")
    assert manifest["enabled"] is False
    assert manifest["failures"] == 3
    assert "skill: auto-disable crash after 3 failures" in _all_commit_subjects(data_paths)

    # It is no longer offered...
    assert "crash" not in skills.list_enabled(data_paths)

    # ...and the NEXT step's context carries the one-time disable notice.
    llm = FakeLLM([_act(), _reflect()])
    loop.run_step(config, data_paths, llm)
    prompt = json.dumps(llm.calls[0]["messages"], ensure_ascii=False)
    assert "turned off automatically" in prompt

    # The notice is one-time: a further step does not repeat it.
    llm2 = FakeLLM([_act(), _reflect()])
    loop.run_step(config, data_paths, llm2)
    prompt2 = json.dumps(llm2.calls[0]["messages"], ensure_ascii=False)
    assert "turned off automatically" not in prompt2


# --------------------------------------------------------------------------- #
# 7. non-stdlib import rejected at write AND at run
# --------------------------------------------------------------------------- #
def test_non_stdlib_import_rejected_at_write(config, data_paths):
    # Via the tool dispatcher (what the agent actually calls).
    res = ktools.dispatch(data_paths, "skill_write",
                          {"name": "np", "description": "d", "code": NONSTDLIB_SKILL})
    payload = json.loads(res.content)
    assert "error" in payload and "numpy" in payload["error"]
    # Nothing was registered.
    assert skills.read_manifest(data_paths, "np") is None
    assert skills.list_enabled(data_paths) == []


def test_non_stdlib_import_rejected_at_run(config, data_paths):
    config.sandbox.backend = "subprocess"
    # A skill that somehow got a non-stdlib import onto disk is caught before it runs.
    _install_skill_directly(data_paths, "np", NONSTDLIB_SKILL)
    result = skill_runner.run_skill(config, data_paths, "np", {"topic": "x"})
    assert result.ok is False
    assert "numpy" in result.error
    # It was not executed (no import error escaped), and the loop-level run is a
    # normal failed step.
    record = _run_skill_step(config, data_paths, "np")
    assert record["kind"] == "wake_step"


def test_run_requirement_and_name_validation():
    ok, _ = skills.check_imports("import json\ndef run(p): return {}\n")
    assert ok is True
    assert skills.has_run("def run(params):\n    return {}\n") is True
    assert skills.has_run("def other():\n    pass\n") is False
    assert skills.valid_skill_name("good-name_1") is True
    assert skills.valid_skill_name("Bad Name") is False
    assert skills.valid_skill_name("-leading") is False


# --------------------------------------------------------------------------- #
# 8. disabled skills are not listed / not offered
# --------------------------------------------------------------------------- #
def test_disabled_skill_not_listed(config, data_paths):
    _install_skill_directly(data_paths, "off", ECHO_SKILL, enabled=False)
    _install_skill_directly(data_paths, "on", ECHO_SKILL, enabled=True)
    assert skills.list_enabled(data_paths) == ["on"]
    names = [a["name"] for a in actions_mod.available_actions(
        skills=skills.list_enabled(data_paths))]
    assert "skill:on" in names
    assert "skill:off" not in names


def test_skills_disabled_globally_offers_no_skill_tools_or_actions(config, data_paths):
    config.skills.enabled = False
    skills.create_skill(data_paths, "greet", "say hi", ECHO_SKILL)
    llm = FakeLLM([_act(), _reflect()])
    loop.run_step(config, data_paths, llm)
    # No skill_write tool offered when skills are globally disabled.
    tool_names = [t["function"]["name"] for t in (llm.calls[0]["tools"] or [])]
    assert "skill_write" not in tool_names
    prompt = json.dumps(llm.calls[0]["messages"], ensure_ascii=False)
    assert "skill:greet" not in prompt
