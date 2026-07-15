"""Function-calling tool schemas + dispatcher for the ACT tool-use loop (P3.5).

Two tool families are exposed to the model during ACT:

    * **wiki** (always offered): ``wiki_search`` / ``wiki_read`` / ``wiki_write`` /
      ``wiki_backlinks`` — a searchable, link-connected knowledge net.
    * **web** (offered too; the agent chooses ``web_explore``): ``web_search`` /
      ``web_read`` / ``arxiv_search`` — imported lazily from
      :mod:`soul.agent.webtools` (written in parallel), so tests that do not
      exercise the web path never need that module.

Descriptions are neutral ("store something you want to find again"); whether to
write or read is entirely the agent's choice. The dispatcher returns a
:class:`DispatchResult` carrying the string the tool round should feed back to
the model plus journal metadata (``wiki_ops`` / ``web_visits``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..paths import DataPaths
from . import wiki


# --------------------------------------------------------------------------- #
# Schemas (OpenAI chat-completions function-calling format)
# --------------------------------------------------------------------------- #
def _fn(name: str, description: str, properties: dict[str, Any],
        required: list[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


WIKI_TOOLS: list[dict[str, Any]] = [
    _fn(
        "wiki_search",
        "search your notes for something you may have written before",
        {"query": {"type": "string", "description": "words to look for"}},
        ["query"],
    ),
    _fn(
        "wiki_read",
        "read one of your stored pages and see what links to it",
        {"slug": {"type": "string", "description": "the page identifier"}},
        ["slug"],
    ),
    _fn(
        "wiki_write",
        "store something you want to find again; use [[other-page]] to link pages",
        {
            "slug": {"type": "string", "description": "a short identifier for the page"},
            "content": {"type": "string", "description": "the page body in markdown"},
        },
        ["slug", "content"],
    ),
    _fn(
        "wiki_backlinks",
        "list the pages that link to a given page",
        {"slug": {"type": "string", "description": "the page identifier"}},
        ["slug"],
    ),
]

WEB_TOOLS: list[dict[str, Any]] = [
    _fn(
        "web_search",
        "look something up beyond your own notes",
        {
            "query": {"type": "string"},
            "max_results": {"type": "integer", "description": "how many results (default 5)"},
        },
        ["query"],
    ),
    _fn(
        "web_read",
        "read the text of a page you found",
        {
            "url": {"type": "string"},
            "max_kb": {"type": "integer", "description": "optional size cap in KB"},
        },
        ["url"],
    ),
    _fn(
        "arxiv_search",
        "look for research papers on a subject",
        {
            "query": {"type": "string"},
            "max_results": {"type": "integer", "description": "how many results (default 5)"},
        },
        ["query"],
    ),
]

WIKI_TOOL_NAMES = frozenset(t["function"]["name"] for t in WIKI_TOOLS)
WEB_TOOL_NAMES = frozenset(t["function"]["name"] for t in WEB_TOOLS)


def act_tools(*, include_web: bool = True) -> list[dict[str, Any]]:
    """Tools offered during ACT (wiki always; web too unless disabled)."""
    return WIKI_TOOLS + WEB_TOOLS if include_web else list(WIKI_TOOLS)


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #
@dataclass
class DispatchResult:
    content: str  # fed back to the model as the tool message content
    wiki_ops: list[dict[str, Any]] = field(default_factory=list)
    web_visits: list[str] = field(default_factory=list)


def _parse_args(arguments: Any) -> dict[str, Any]:
    """Tool-call arguments arrive as a JSON string (OpenAI) or a dict."""
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            obj = json.loads(arguments or "{}")
            return obj if isinstance(obj, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def dispatch(
    paths: DataPaths,
    name: str,
    arguments: Any,
    *,
    web_config: Any | None = None,
) -> DispatchResult:
    """Execute one tool call and return its result + journal metadata.

    Never raises for a tool-level failure: an error is returned as the tool
    message content so the model can react, keeping the loop alive.
    """
    args = _parse_args(arguments)
    try:
        if name == "wiki_search":
            hits = wiki.search(paths, str(args.get("query", "")))
            return DispatchResult(content=json.dumps(hits, ensure_ascii=False))

        if name == "wiki_read":
            page = wiki.read_page(paths, str(args.get("slug", "")))
            if page is None:
                return DispatchResult(content=json.dumps({"error": "not found"}))
            return DispatchResult(content=json.dumps(page, ensure_ascii=False))

        if name == "wiki_write":
            slug = str(args.get("slug", ""))
            info = wiki.write_page(paths, slug, str(args.get("content", "")))
            return DispatchResult(
                content=json.dumps({"stored": info["slug"], "title": info["title"]},
                                   ensure_ascii=False),
                wiki_ops=[{"tool": "wiki_write", "slug": info["slug"]}],
            )

        if name == "wiki_backlinks":
            slug = str(args.get("slug", ""))
            links = wiki.backlinks(paths, slug)
            return DispatchResult(content=json.dumps({"backlinks": links}, ensure_ascii=False))

        if name in WEB_TOOL_NAMES:
            return _dispatch_web(name, args, web_config)

    except Exception as exc:  # noqa: BLE001 — tool failures must not kill the loop
        return DispatchResult(content=json.dumps({"error": str(exc)}, ensure_ascii=False))

    return DispatchResult(content=json.dumps({"error": f"unknown tool: {name}"}))


def _dispatch_web(name: str, args: dict[str, Any], web_config: Any | None) -> DispatchResult:
    """Lazily import webtools so the web path is optional (spec: import inside)."""
    from ..agent import webtools  # imported lazily; mocked in tests

    if name == "web_search":
        results = webtools.web_search(
            str(args.get("query", "")),
            max_results=int(args.get("max_results", 5) or 5),
        )
        return DispatchResult(content=json.dumps(results, ensure_ascii=False))

    if name == "web_read":
        max_kb = args.get("max_kb")
        result = webtools.web_read(
            str(args.get("url", "")),
            max_kb=int(max_kb) if max_kb is not None else None,
        )
        url = result.get("url") if isinstance(result, dict) else str(args.get("url", ""))
        return DispatchResult(
            content=json.dumps(result, ensure_ascii=False),
            web_visits=[url] if url else [],
        )

    if name == "arxiv_search":
        results = webtools.arxiv_search(
            str(args.get("query", "")),
            max_results=int(args.get("max_results", 5) or 5),
        )
        return DispatchResult(content=json.dumps(results, ensure_ascii=False))

    return DispatchResult(content=json.dumps({"error": f"unknown web tool: {name}"}))
