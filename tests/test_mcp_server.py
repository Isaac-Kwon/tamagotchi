"""Read-only MCP server tests (M9, spec P3.5).

Two layers, per the milestone brief:

    * The tool *functions* (:mod:`soul.knowledge.mcp_server`) are tested
      directly against a seeded ``data_paths`` fixture — no MCP transport
      involved. This covers the read-only guarantees precisely (read-only
      SQLite connection, no index-rebuild side effect by default, clear
      not-found messages instead of exceptions).
    * One in-process MCP client/session round-trip test
      (``test_mcp_roundtrip_over_client_session``), using the SDK's
      ``mcp.shared.memory.create_connected_server_and_client_session`` helper
      to drive the actual server object through ``list_tools``/``call_tool``
      without spawning a subprocess or touching stdio.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from soul.knowledge import mcp_server as ms
from soul.knowledge import wiki
from soul.paths import DataPaths
from soul.storage import journal


# --------------------------------------------------------------------------- #
# Fixtures: seed a wiki page, journal steps, a report, and a transcript.
# --------------------------------------------------------------------------- #
@pytest.fixture
def seeded(data_paths: DataPaths) -> DataPaths:
    wiki.write_page(
        data_paths,
        "quantum-notes",
        "# Quantum Notes\n\nnotes on entanglement, see [[other-topic]].",
        commit=False,
    )
    wiki.write_page(
        data_paths,
        "other-topic",
        "# Other Topic\n\nunrelated body text.",
        commit=False,
    )

    journal.append_step(
        data_paths,
        journal.new_step_record(
            "step-000001",
            ts="2026-07-14T10:00:00+00:00",
            action="free_write",
            topic="entanglement",
            interest=6,
            summary="Wrote about entanglement.",
        ),
    )
    journal.append_step(
        data_paths,
        journal.new_step_record(
            "step-000002",
            ts="2026-07-15T10:00:00+00:00",
            action="revisit_notes",
            topic="entanglement",
            interest=8,
            summary="Revisited entanglement notes.",
        ),
    )

    data_paths.reports_dir.mkdir(parents=True, exist_ok=True)
    (data_paths.reports_dir / "2026-07-15.md").write_text(
        "# 2026-07-15\n\nA quiet day of reading.\n", encoding="utf-8"
    )

    data_paths.transcripts_dir.mkdir(parents=True, exist_ok=True)
    tpath = data_paths.transcript_file("step-000002")
    with tpath.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"role": "system", "content": "act"}) + "\n")
        fh.write(json.dumps({"role": "assistant", "content": "{}"}) + "\n")

    return data_paths


# --------------------------------------------------------------------------- #
# wiki_search
# --------------------------------------------------------------------------- #
def test_wiki_search_hits(seeded):
    hits = ms.wiki_search(seeded, "entanglement")
    assert isinstance(hits, list)
    assert any(h["slug"] == "quantum-notes" for h in hits)


def test_wiki_search_empty_query(seeded):
    assert ms.wiki_search(seeded, "") == []


def test_wiki_search_no_index_returns_hint_not_exception(data_paths):
    # Fresh data dir: no wiki pages written yet, so no index exists.
    assert not data_paths.wiki_index_db.exists()
    result = ms.wiki_search(data_paths, "anything")
    assert isinstance(result, dict)
    assert "error" in result
    assert "index" in result["error"]
    # Read-only by default: the index must still not exist afterwards.
    assert not data_paths.wiki_index_db.exists()


def test_wiki_search_allow_index_rebuild_opt_in(seeded):
    # Delete the derived index; write_page already built it, so remove it to
    # simulate an external corruption/staleness scenario.
    seeded.wiki_index_db.unlink()
    assert not seeded.wiki_index_db.exists()

    # Default (no opt-in): hint, no rebuild.
    result = ms.wiki_search(seeded, "entanglement")
    assert "error" in result
    assert not seeded.wiki_index_db.exists()

    # Opt-in: rebuilds the derived index (not the markdown) then searches.
    result2 = ms.wiki_search(seeded, "entanglement", allow_index_rebuild=True)
    assert isinstance(result2, list)
    assert seeded.wiki_index_db.exists()


# --------------------------------------------------------------------------- #
# wiki_read / wiki_list
# --------------------------------------------------------------------------- #
def test_wiki_read_found_with_backlinks(seeded):
    page = ms.wiki_read(seeded, "other-topic")
    assert page["slug"] == "other-topic"
    assert "unrelated body text" in page["body"]
    assert page["backlinks"] == ["quantum-notes"]


def test_wiki_read_not_found_is_message_not_exception(seeded):
    result = ms.wiki_read(seeded, "does-not-exist")
    assert "error" in result
    assert "does-not-exist" in result["error"]


def test_wiki_list(seeded):
    pages = ms.wiki_list(seeded)
    slugs = {p["slug"] for p in pages}
    assert slugs == {"quantum-notes", "other-topic"}


# --------------------------------------------------------------------------- #
# read_soul
# --------------------------------------------------------------------------- #
def test_read_soul_returns_seeded_content(seeded):
    result = ms.read_soul(seeded)
    assert "content" in result
    assert "owned and edited only by the agent itself" in result["content"]


def test_read_soul_missing_is_message_not_exception(tmp_path):
    # A DataPaths pointed at a directory with no SOUL.md at all (never seeded).
    bare = DataPaths(tmp_path / "bare")
    bare.root.mkdir(parents=True)
    result = ms.read_soul(bare)
    assert "error" in result
    # Crucially: read_soul must NOT have created SOUL.md as a side effect.
    assert not bare.soul_md.exists()


# --------------------------------------------------------------------------- #
# query_journal
# --------------------------------------------------------------------------- #
def test_query_journal_returns_all_within_limit(seeded):
    steps = ms.query_journal(seeded, limit=20)
    assert [s["id"] for s in steps] == ["step-000001", "step-000002"]


def test_query_journal_limit(seeded):
    steps = ms.query_journal(seeded, limit=1)
    assert [s["id"] for s in steps] == ["step-000002"]


def test_query_journal_since_filters(seeded):
    steps = ms.query_journal(seeded, since="2026-07-15T00:00:00+00:00")
    assert [s["id"] for s in steps] == ["step-000002"]


def test_query_journal_empty_journal(data_paths):
    assert ms.query_journal(data_paths) == []


# --------------------------------------------------------------------------- #
# read_report
# --------------------------------------------------------------------------- #
def test_read_report_found(seeded):
    result = ms.read_report(seeded, "2026-07-15")
    assert result["date"] == "2026-07-15"
    assert "quiet day" in result["content"]


def test_read_report_missing_is_message_not_exception(seeded):
    result = ms.read_report(seeded, "1999-01-01")
    assert "error" in result
    assert "1999-01-01" in result["error"]


# --------------------------------------------------------------------------- #
# read_transcript
# --------------------------------------------------------------------------- #
def test_read_transcript_found(seeded):
    result = ms.read_transcript(seeded, "step-000002")
    assert result["step_id"] == "step-000002"
    assert len(result["entries"]) == 2
    assert result["entries"][0]["role"] == "system"


def test_read_transcript_missing_is_message_not_exception(seeded):
    result = ms.read_transcript(seeded, "step-999999")
    assert "error" in result
    assert "step-999999" in result["error"]


# --------------------------------------------------------------------------- #
# Read-only enforcement at the SQLite layer
# --------------------------------------------------------------------------- #
def test_index_connection_is_actually_read_only(seeded):
    conn = ms._connect_ro(seeded.wiki_index_db)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO pages(slug, title, body, mtime, updated_at) "
                         "VALUES ('x','x','x',0,'x')")
            conn.commit()
    finally:
        conn.close()


def test_wiki_read_does_not_touch_index_when_missing(seeded):
    seeded.wiki_index_db.unlink()
    result = ms.wiki_read(seeded, "quantum-notes")
    # Backlinks silently degrade to [] with a note, rather than rebuilding.
    assert result["backlinks"] == []
    assert "backlinks_note" in result
    assert not seeded.wiki_index_db.exists()


# --------------------------------------------------------------------------- #
# In-process MCP client/server round trip (one test, per the milestone brief)
# --------------------------------------------------------------------------- #
def test_mcp_roundtrip_over_client_session(seeded):
    anyio = pytest.importorskip("anyio")
    from mcp.shared.memory import create_connected_server_and_client_session

    async def _run():
        server = ms.build_server(seeded.root)
        async with create_connected_server_and_client_session(
            server._mcp_server
        ) as client:
            tools = await client.list_tools()
            names = {t.name for t in tools.tools}
            assert names == {
                "wiki_search", "wiki_read", "wiki_list", "read_soul",
                "query_journal", "read_report", "read_transcript",
            }

            result = await client.call_tool("read_soul", {})
            assert result.isError is False
            assert "owned and edited only" in result.structuredContent["content"]

            result = await client.call_tool("wiki_read", {"slug": "quantum-notes"})
            assert result.isError is False
            assert result.structuredContent["slug"] == "quantum-notes"

            result = await client.call_tool("wiki_read", {"slug": "nope"})
            assert result.isError is False  # a not-found message, not a protocol error
            assert "error" in result.structuredContent

            result = await client.call_tool("query_journal", {"limit": 1})
            assert result.isError is False
            assert result.structuredContent["result"][0]["id"] == "step-000002"

    anyio.run(_run)
