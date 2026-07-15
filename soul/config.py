"""Configuration loading and validation for the Soul Tamagotchi agent.

The configuration format is JSON (spec P6). This module loads ``config.json``
into a set of validated dataclasses. API-key resolution order:

    1. ``llm.api_key`` written directly in the config
    2. the environment variable named by ``llm.api_key_env``
    3. otherwise no key — requests are sent without an Authorization header,
       which is what local OpenAI-compatible endpoints (e.g. Ollama) expect

When ``llm.mock`` is true (or ``--mock`` is passed on the command line), the
runtime substitutes a FakeLLM and no endpoint is contacted at all.
"""

from __future__ import annotations

import ipaddress
import json
import os
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any


class ConfigError(Exception):
    """Raised when configuration is missing or invalid. Message is user-facing."""


# --------------------------------------------------------------------------- #
# Dataclasses mirroring the config.json schema (spec P6)
# --------------------------------------------------------------------------- #
@dataclass
class LLMConfig:
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    api_key_env: str = "OPENAI_API_KEY"
    api_key: str | None = None
    timeout_seconds: int = 120
    max_retries: int = 3
    temperature: float = 1.0
    max_output_tokens: int = 2000
    mock: bool = False


@dataclass
class AgentConfig:
    data_dir: str = "./data"
    mode: str = "heartbeat"  # "heartbeat" | "continuous"
    heartbeat_minutes: int = 30
    min_step_gap_seconds: int = 60
    step_timeout_minutes: int = 45
    context_recent_steps: int = 10
    serendipity_rate: float = 0.3
    soul_max_chars: int = 8000
    consecutive_error_backoff: int = 5


@dataclass
class ChatConfig:
    record_default: bool = False
    idle_end_seconds: int = 180
    preempt_max_wait_minutes: int = 30
    preempt_poll_seconds: int = 2


@dataclass
class SandboxConfig:
    enabled: bool = True
    timeout_seconds: int = 10
    backend: str = "auto"


@dataclass
class SkillsConfig:
    enabled: bool = True
    timeout_seconds: int = 20
    auto_disable_after_failures: int = 3


@dataclass
class WebActionsConfig:
    enabled: bool = True
    http_timeout_seconds: int = 20
    max_page_kb: int = 500


@dataclass
class KnowledgeConfig:
    max_tool_rounds: int = 5
    fts_snippet_len: int = 200


@dataclass
class ReportConfig:
    time: str = "22:00"
    timezone: str = "Asia/Seoul"
    language: str = "ko"


@dataclass
class WebConfig:
    host: str = "127.0.0.1"
    port: int = 8000
    sse_check_ms: int = 1000
    # CIDR allowlist for the web server ("192.168.0.0/24", "10.0.0.5/32", ...).
    # Empty list = no filtering (the default 127.0.0.1 bind already limits
    # access to the local machine). When non-empty, requests from addresses
    # outside every listed network are rejected with 403.
    allowed_networks: list[str] = field(default_factory=list)

    def parsed_networks(self) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
        """``allowed_networks`` parsed into network objects (may raise ValueError)."""
        return [ipaddress.ip_network(n, strict=False) for n in self.allowed_networks]


@dataclass
class Config:
    llm: LLMConfig = field(default_factory=LLMConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    chat: ChatConfig = field(default_factory=ChatConfig)
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    skills: SkillsConfig = field(default_factory=SkillsConfig)
    web_actions: WebActionsConfig = field(default_factory=WebActionsConfig)
    knowledge: KnowledgeConfig = field(default_factory=KnowledgeConfig)
    report: ReportConfig = field(default_factory=ReportConfig)
    web: WebConfig = field(default_factory=WebConfig)

    # Populated after resolution; not part of the JSON schema.
    resolved_api_key: str | None = None

    def data_path(self) -> Path:
        """Absolute path to the agent data directory."""
        return Path(self.agent.data_dir).expanduser().resolve()


# --------------------------------------------------------------------------- #
# Loading helpers
# --------------------------------------------------------------------------- #
def _build_section(cls: type, raw: Any, section_name: str) -> Any:
    """Instantiate a dataclass ``cls`` from a raw dict, rejecting unknown keys."""
    if raw is None:
        return cls()
    if not isinstance(raw, dict):
        raise ConfigError(
            f"Config section '{section_name}' must be a JSON object, "
            f"got {type(raw).__name__}."
        )
    known = {f.name for f in fields(cls)}
    unknown = set(raw) - known
    if unknown:
        raise ConfigError(
            f"Config section '{section_name}' has unknown keys: "
            f"{', '.join(sorted(unknown))}."
        )
    return cls(**raw)


def config_from_dict(raw: dict[str, Any]) -> Config:
    """Build a :class:`Config` from a parsed JSON dict, validating structure."""
    if not isinstance(raw, dict):
        raise ConfigError("Top-level config must be a JSON object.")

    known_sections = {f.name for f in fields(Config) if is_dataclass(f.type) or True}
    section_types = {
        "llm": LLMConfig,
        "agent": AgentConfig,
        "chat": ChatConfig,
        "sandbox": SandboxConfig,
        "skills": SkillsConfig,
        "web_actions": WebActionsConfig,
        "knowledge": KnowledgeConfig,
        "report": ReportConfig,
        "web": WebConfig,
    }
    unknown = set(raw) - set(section_types)
    if unknown:
        raise ConfigError(
            f"Config has unknown top-level sections: {', '.join(sorted(unknown))}."
        )

    kwargs: dict[str, Any] = {}
    for name, cls in section_types.items():
        kwargs[name] = _build_section(cls, raw.get(name), name)

    cfg = Config(**kwargs)
    _validate(cfg)
    return cfg


def _validate(cfg: Config) -> None:
    """Range/enum validation beyond structural checks."""
    if cfg.agent.mode not in ("heartbeat", "continuous"):
        raise ConfigError(
            f"agent.mode must be 'heartbeat' or 'continuous', got "
            f"{cfg.agent.mode!r}."
        )
    if not 0.0 <= cfg.agent.serendipity_rate <= 1.0:
        raise ConfigError("agent.serendipity_rate must be between 0 and 1.")
    if cfg.agent.context_recent_steps < 0:
        raise ConfigError("agent.context_recent_steps must be >= 0.")
    if cfg.agent.soul_max_chars <= 0:
        raise ConfigError("agent.soul_max_chars must be > 0.")
    if cfg.llm.max_retries < 1:
        raise ConfigError("llm.max_retries must be >= 1.")
    if cfg.llm.timeout_seconds <= 0:
        raise ConfigError("llm.timeout_seconds must be > 0.")
    try:
        cfg.web.parsed_networks()
    except ValueError as exc:
        raise ConfigError(
            f"web.allowed_networks has an invalid CIDR entry: {exc}"
        ) from exc


def resolve_api_key(cfg: Config, *, mock_override: bool = False) -> None:
    """Resolve the LLM API key in place (config value, then env var).

    ``mock_override`` reflects a ``--mock`` command-line flag; combined with
    ``llm.mock`` it skips resolution entirely.

    A missing key is NOT an error: local OpenAI-compatible endpoints (Ollama
    etc.) take requests without an Authorization header, so the client simply
    omits it when ``resolved_api_key`` stays ``None``.
    """
    if cfg.llm.mock or mock_override:
        cfg.llm.mock = True
        cfg.resolved_api_key = None
        return

    if cfg.llm.api_key:
        cfg.resolved_api_key = cfg.llm.api_key
        return

    env_name = cfg.llm.api_key_env
    if env_name and os.environ.get(env_name):
        cfg.resolved_api_key = os.environ[env_name]
        return

    cfg.resolved_api_key = None


def load_config(
    path: str | os.PathLike[str] = "config.json",
    *,
    mock_override: bool = False,
) -> Config:
    """Load and validate configuration from ``path``.

    Raises :class:`ConfigError` with a user-facing message on any problem,
    including a missing file.
    """
    p = Path(path)
    if not p.exists():
        raise ConfigError(
            f"Config file not found: {p}\n"
            "Copy config.example.json to config.json and edit it."
        )
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Config file {p} is not valid JSON: {exc}") from exc

    cfg = config_from_dict(raw)
    resolve_api_key(cfg, mock_override=mock_override)
    return cfg
