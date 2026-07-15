"""Entry point for the read-only knowledge MCP server (spec P3.5, M9).

    python run_mcp.py                        # serve ./data over stdio
    python run_mcp.py --data-dir ./data       # explicit data directory
    python run_mcp.py --allow-index-rebuild   # opt-in: build the wiki FTS
                                               # index itself if missing/stale
                                               # (off by default — see below)

This process is **strictly read-only**: it never writes SOUL.md, the journal,
reports, transcripts, or the wiki markdown, and it opens the wiki's derived
SQLite index (``index/wiki.sqlite3``) with a read-only connection
(``file:...?mode=ro``). The write principle of the whole system is that
exactly one process — the agent loop (``run_agent.py``) — ever writes the
data directory; this server, like the API server, only reads it (spec P1/P5).

If the wiki index has not been built yet (or is stale), tools return a clear
message asking you to run the agent instead of silently rebuilding it, unless
you explicitly pass ``--allow-index-rebuild`` (a narrow, opt-in exception: it
only rewrites the *derived* index, never the markdown source, and only when
you have asked for it).

Register with Claude Code (or any MCP client that can launch a stdio server)::

    claude mcp add soul-wiki -- python run_mcp.py --data-dir ./data

Once registered, an external AI can call ``wiki_search``, ``wiki_read``,
``wiki_list``, ``read_soul``, ``query_journal``, ``read_report``, and
``read_transcript`` against the running soul's data for structural diagnosis.
"""

from __future__ import annotations

import argparse
import sys

from soul.knowledge.mcp_server import serve_stdio


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only MCP server exposing a Soul Tamagotchi agent's wiki, "
            "SOUL.md, journal, reports, and transcripts over stdio. Register "
            "with: claude mcp add soul-wiki -- python run_mcp.py --data-dir ./data"
        )
    )
    parser.add_argument(
        "--data-dir", default="./data", help="Path to the agent's data directory (default ./data)"
    )
    parser.add_argument(
        "--allow-index-rebuild",
        action="store_true",
        help=(
            "Opt-in: rebuild the wiki's derived SQLite index (index/wiki.sqlite3) "
            "if it is missing, instead of returning a message telling you to run "
            "the agent. Never touches the wiki markdown itself. Default: off."
        ),
    )
    args = parser.parse_args(argv)

    print(
        f"soul-wiki MCP server: data_dir={args.data_dir} "
        f"allow_index_rebuild={args.allow_index_rebuild} (read-only, stdio)",
        file=sys.stderr,
    )
    serve_stdio(args.data_dir, allow_index_rebuild=args.allow_index_rebuild)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
