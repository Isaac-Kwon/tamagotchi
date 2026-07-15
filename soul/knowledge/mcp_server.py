"""Read-only MCP server for external diagnosis of a soul's data directory (spec P3.5).

Exposes the wiki, SOUL.md, journal, daily reports, and step transcripts to an
external AI (e.g. Claude Code) over the Model Context Protocol, using the
official ``mcp`` Python SDK (:class:`~mcp.server.fastmcp.FastMCP`) and the
stdio transport. Register it with::

    claude mcp add soul-wiki -- python run_mcp.py --data-dir ./data

**Strictly read-only.** The write principle of the whole system (spec P1/P5)
is that exactly one process — the agent loop — ever writes the data
directory; the API server and this MCP server only read it. Concretely:

    * The wiki's derived SQLite FTS index (``index/wiki.sqlite3``) is opened
      with a read-only connection (``file:...?mode=ro``), so even a bug here
      cannot corrupt it.
    * If that index is missing or stale, this server does **not** rebuild it
      by default — rebuilding is a write, and the agent process already
      rebuilds it automatically on its own startup/search calls (see
      :func:`soul.knowledge.wiki.ensure_index`). Instead, tools return a
      clear, non-exception message telling the caller to run the agent (or
      pass ``--allow-index-rebuild`` to this server if an explicit opt-in
      rebuild is wanted).
    * SOUL.md, journal files, reports, and transcripts are read directly with
      plain file reads — never seeded, never (re)written — so a request for a
      resource that does not exist yet returns a clear "not found" message
      rather than creating one (unlike, e.g., :func:`soul.agent.soul.read_soul`,
      which seeds SOUL.md if absent and is therefore *not* used here).

Every tool function below takes a :class:`~soul.paths.DataPaths` as its first
argument and returns a plain, JSON-friendly value (dict/list/str) — never
raises for a missing resource — so they can be unit-tested directly, without
going through an MCP client/transport.
"""

from __future__ import annotations

import json
import sqlite3
import urllib.parse
from pathlib import Path
from typing import Any

from ..paths import DataPaths
from ..storage import journal as journal_store
from . import wiki as wiki_mod

#: Shown to the caller instead of raising when the FTS index has not been
#: built yet and this server was not started with --allow-index-rebuild.
_INDEX_MISSING_HINT = (
    "wiki index not built yet (index/wiki.sqlite3 is missing). The agent "
    "process builds it automatically (soul.knowledge.wiki.ensure_index) the "
    "next time it runs a wiki tool or step — run `python run_agent.py "
    "--once --mock` (or a real step) to build it, or restart this MCP "
    "server with --allow-index-rebuild to let it build the index itself."
)


# --------------------------------------------------------------------------- #
# Small local helpers (kept independent of wiki.py's read/write helpers,
# several of which trigger an index rebuild as a side effect — see module
# docstring).
# --------------------------------------------------------------------------- #
def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return out


def _derive_title(slug: str, body: str, frontmatter: dict[str, str]) -> str:
    if frontmatter.get("title"):
        return frontmatter["title"]
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return slug.replace("-", " ")


def _ro_uri(db_path: Path) -> str:
    """A sqlite3 URI filename opening ``db_path`` read-only (``mode=ro``)."""
    return "file:" + urllib.parse.quote(db_path.as_posix()) + "?mode=ro"


def _connect_ro(db_path: Path) -> sqlite3.Connection:
    """Open the wiki index with a strictly read-only SQLite connection.

    Caller must ensure ``db_path.exists()`` first — ``mode=ro`` on a missing
    file raises ``sqlite3.OperationalError``, which we turn into the friendly
    :data:`_INDEX_MISSING_HINT` message one level up instead of surfacing.
    """
    return sqlite3.connect(_ro_uri(db_path), uri=True)


def _fts_query(query: str) -> str:
    """Sanitize free text into a safe FTS5 MATCH expression (bare words ORed).

    Mirrors :func:`soul.knowledge.wiki._fts_query` so search behaves the same
    from the outside; duplicated (rather than imported) because it is a tiny,
    private, pure helper and this module intentionally avoids depending on
    wiki.py internals that carry write side effects.
    """
    import re

    tokens = re.findall(r"[A-Za-z0-9_]+", query)
    if not tokens:
        return '""'
    return " OR ".join(tokens)


# --------------------------------------------------------------------------- #
# Tool implementations — plain functions, unit-testable without an MCP client.
# --------------------------------------------------------------------------- #
def wiki_search(
    paths: DataPaths,
    query: str,
    *,
    limit: int = 10,
    allow_index_rebuild: bool = False,
) -> list[dict[str, Any]] | dict[str, str]:
    """Full-text search the wiki. Returns ``[{slug, title, snippet}, ...]``.

    Read-only: opens ``index/wiki.sqlite3`` with a ``mode=ro`` SQLite
    connection. If the index does not exist, returns ``{"error": <hint>}``
    unless ``allow_index_rebuild`` is set (server ``--allow-index-rebuild``
    flag), in which case it is built once via
    :func:`soul.knowledge.wiki.rebuild_index` before searching.
    """
    query = (query or "").strip()
    if not query:
        return []
    if not paths.wiki_index_db.exists():
        if allow_index_rebuild:
            wiki_mod.rebuild_index(paths)
        else:
            return {"error": _INDEX_MISSING_HINT}
    try:
        conn = _connect_ro(paths.wiki_index_db)
    except sqlite3.OperationalError:
        return {"error": _INDEX_MISSING_HINT}
    try:
        try:
            rows = conn.execute(
                """
                SELECT slug, title,
                       snippet(pages_fts, 2, '[', ']', ' ... ', 20) AS snip
                FROM pages_fts
                WHERE pages_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (_fts_query(query), max(1, limit)),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            return {"error": f"index query failed: {exc}"}
        return [{"slug": r[0], "title": r[1], "snippet": r[2]} for r in rows]
    finally:
        conn.close()


def _backlinks_ro(paths: DataPaths, slug: str) -> list[str] | None:
    """Read-only backlink lookup. Returns None (not []) if the index is absent."""
    if not paths.wiki_index_db.exists():
        return None
    try:
        conn = _connect_ro(paths.wiki_index_db)
    except sqlite3.OperationalError:
        return None
    try:
        try:
            rows = conn.execute(
                "SELECT DISTINCT src FROM links WHERE dst = ? ORDER BY src", (slug,)
            ).fetchall()
        except sqlite3.OperationalError:
            return None
        return [r[0] for r in rows]
    finally:
        conn.close()


def wiki_read(paths: DataPaths, slug: str) -> dict[str, Any]:
    """Read one wiki page's frontmatter, body, outgoing links, and backlinks.

    Read-only: the page body comes straight from ``wiki/<slug>.md``; backlinks
    come from a read-only query of the derived index (``null``/omitted with a
    note if the index has not been built — this never triggers a rebuild).
    Returns ``{"error": "not found: <slug>"}`` (not an exception) for a
    missing page.
    """
    slug = wiki_mod.slugify(slug)
    path = paths.wiki_file(slug)
    if not path.exists():
        return {"error": f"not found: no wiki page '{slug}'"}
    fm, body = wiki_mod.parse_page(path.read_text(encoding="utf-8"))
    backlinks = _backlinks_ro(paths, slug)
    result: dict[str, Any] = {
        "slug": slug,
        "title": _derive_title(slug, body, fm),
        "frontmatter": fm,
        "body": body,
        "links": wiki_mod.extract_links(body),
        "backlinks": backlinks if backlinks is not None else [],
    }
    if backlinks is None:
        result["backlinks_note"] = (
            "index not built yet, so backlinks could not be computed " + _INDEX_MISSING_HINT
        )
    return result


def wiki_list(paths: DataPaths) -> list[dict[str, str]]:
    """List all wiki pages as ``[{slug, title}, ...]``, read directly from the md files."""
    return wiki_mod.list_pages(paths)


def read_soul(paths: DataPaths) -> dict[str, Any]:
    """Read SOUL.md verbatim. Never seeds/creates it (unlike ``soul.agent.soul.read_soul``)."""
    if not paths.soul_md.exists():
        return {"error": "not found: SOUL.md does not exist in this data directory yet"}
    return {"content": paths.soul_md.read_text(encoding="utf-8")}


def query_journal(
    paths: DataPaths, limit: int = 20, since: str | None = None
) -> list[dict[str, Any]]:
    """Return recent journal step records, in chronological order (oldest first).

    ``since`` (optional) is an ISO-8601 timestamp string; only steps with
    ``ts >= since`` are kept. After that filter, the most recent ``limit``
    records are returned (``limit <= 0`` returns everything that matched).
    Reads the monthly JSONL journal files directly; never writes.
    """
    records = journal_store.read_all(paths)
    if since:
        records = [r for r in records if (r.get("ts") or "") >= since]
    if limit and limit > 0:
        records = records[-limit:]
    return records


def read_report(paths: DataPaths, date: str) -> dict[str, Any]:
    """Read the daily retrospective report for ``date`` ("YYYY-MM-DD")."""
    path = paths.reports_dir / f"{date}.md"
    if not path.exists():
        return {"error": f"not found: no report for {date}"}
    return {"date": date, "content": path.read_text(encoding="utf-8")}


def read_transcript(paths: DataPaths, step_id: str) -> dict[str, Any]:
    """Read the full LLM round-trip transcript (JSONL entries) for ``step_id``."""
    path = paths.transcript_file(step_id)
    if not path.exists():
        return {"error": f"not found: no transcript for step '{step_id}'"}
    return {"step_id": step_id, "entries": _read_jsonl(path)}


# --------------------------------------------------------------------------- #
# MCP server wiring (FastMCP, stdio transport)
# --------------------------------------------------------------------------- #
_SERVER_INSTRUCTIONS = """\
Read-only diagnostic access to a Soul Tamagotchi agent's data directory: its
searchable notes wiki, self-description (SOUL.md), step journal, daily
retrospective reports, and per-step LLM transcripts. Nothing here can be
written — the agent process is the sole writer of this data (spec P1/P5).
"""


def build_server(data_dir: str | Path, *, allow_index_rebuild: bool = False) -> Any:
    """Build (but do not run) the FastMCP server bound to ``data_dir``.

    Returns a :class:`mcp.server.fastmcp.FastMCP` instance; call ``.run()`` /
    ``.run(transport="stdio")`` on it to serve. Kept separate from
    :func:`serve_stdio` so tests can build a server and drive it in-process
    (e.g. with ``mcp.shared.memory.create_connected_server_and_client_session``)
    without spawning a subprocess.
    """
    from mcp.server.fastmcp import FastMCP

    paths = DataPaths(data_dir)
    mcp = FastMCP(name="soul-wiki", instructions=_SERVER_INSTRUCTIONS)

    @mcp.tool(name="wiki_search", description=wiki_search.__doc__)
    def _tool_wiki_search(
        query: str, limit: int = 10
    ) -> list[dict[str, Any]] | dict[str, str]:
        return wiki_search(paths, query, limit=limit, allow_index_rebuild=allow_index_rebuild)

    @mcp.tool(name="wiki_read", description=wiki_read.__doc__)
    def _tool_wiki_read(slug: str) -> dict[str, Any]:
        return wiki_read(paths, slug)

    @mcp.tool(name="wiki_list", description=wiki_list.__doc__)
    def _tool_wiki_list() -> list[dict[str, str]]:
        return wiki_list(paths)

    @mcp.tool(name="read_soul", description=read_soul.__doc__)
    def _tool_read_soul() -> dict[str, Any]:
        return read_soul(paths)

    @mcp.tool(name="query_journal", description=query_journal.__doc__)
    def _tool_query_journal(limit: int = 20, since: str | None = None) -> list[dict[str, Any]]:
        return query_journal(paths, limit=limit, since=since)

    @mcp.tool(name="read_report", description=read_report.__doc__)
    def _tool_read_report(date: str) -> dict[str, Any]:
        return read_report(paths, date)

    @mcp.tool(name="read_transcript", description=read_transcript.__doc__)
    def _tool_read_transcript(step_id: str) -> dict[str, Any]:
        return read_transcript(paths, step_id)

    return mcp


def serve_stdio(data_dir: str | Path, *, allow_index_rebuild: bool = False) -> None:
    """Build the server and serve it over stdio (blocks until the client disconnects)."""
    server = build_server(data_dir, allow_index_rebuild=allow_index_rebuild)
    server.run(transport="stdio")
