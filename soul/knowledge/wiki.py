"""Knowledge wiki — markdown source + derived SQLite FTS index (spec P3.5).

Storage (diagnosability + searchability at once):
    * **Source**: ``data/wiki/<slug>.md`` — frontmatter + body, with
      ``[[other-page]]`` links forming a wiki-style net. Committed to the data
      git repo so knowledge growth is observable as a diff.
    * **Derived index**: ``data/index/wiki.sqlite3`` — ``pages``, ``links(src,
      dst)`` (backlink graph), and an FTS5 ``pages_fts`` table. Always fully
      rebuildable from the md files (:func:`rebuild_index`); startup calls
      :func:`ensure_index`, which rebuilds when file mtimes disagree with the
      index. Never committed.

sqlite3 + FTS5 are stdlib — zero extra dependencies.
"""

from __future__ import annotations

import re
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..paths import DataPaths

# [[target]] or [[target|display text]] — capture the target.
_LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_HEADING_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Slugs, frontmatter, links
# --------------------------------------------------------------------------- #
def slugify(text: str) -> str:
    """Normalize a title or link target to a filesystem-safe slug."""
    s = _SLUG_RE.sub("-", (text or "").strip().lower()).strip("-")
    return s or "untitled"


def parse_page(text: str) -> tuple[dict[str, str], str]:
    """Split a page into ``(frontmatter_dict, body)``.

    Frontmatter is an optional ``---`` delimited block of ``key: value`` lines at
    the very top. Absent frontmatter yields an empty dict.
    """
    if text.startswith("---"):
        lines = text.splitlines()
        # lines[0] is the opening '---'; find the closing one.
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                fm: dict[str, str] = {}
                for raw in lines[1:i]:
                    if ":" in raw:
                        key, _, val = raw.partition(":")
                        fm[key.strip()] = val.strip()
                body = "\n".join(lines[i + 1 :]).lstrip("\n")
                return fm, body
    return {}, text


def render_page(frontmatter: dict[str, str], body: str) -> str:
    """Render frontmatter + body back to a full md document."""
    lines = ["---"]
    for key, val in frontmatter.items():
        lines.append(f"{key}: {val}")
    lines.append("---")
    return "\n".join(lines) + "\n" + body.rstrip("\n") + "\n"


def extract_links(body: str) -> list[str]:
    """Return the de-duplicated list of link target slugs found in ``body``."""
    seen: list[str] = []
    for match in _LINK_RE.finditer(body):
        slug = slugify(match.group(1))
        if slug not in seen:
            seen.append(slug)
    return seen


def _derive_title(slug: str, body: str, frontmatter: dict[str, str]) -> str:
    if frontmatter.get("title"):
        return frontmatter["title"]
    heading = _HEADING_RE.search(body)
    if heading:
        return heading.group(1).strip()
    return slug.replace("-", " ")


# --------------------------------------------------------------------------- #
# SQLite index
# --------------------------------------------------------------------------- #
def _connect(paths: DataPaths) -> sqlite3.Connection:
    paths.index_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(paths.wiki_index_db))
    conn.row_factory = sqlite3.Row
    return conn


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS pages (
            slug TEXT PRIMARY KEY,
            title TEXT,
            body TEXT,
            mtime REAL,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS links (
            src TEXT,
            dst TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_links_dst ON links(dst);
        CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts
            USING fts5(slug, title, body);
        """
    )


def _index_page(conn: sqlite3.Connection, slug: str, path: Path) -> None:
    """(Re)index a single page from its md file into an open connection."""
    text = path.read_text(encoding="utf-8")
    fm, body = parse_page(text)
    title = _derive_title(slug, body, fm)
    mtime = path.stat().st_mtime

    conn.execute("DELETE FROM pages WHERE slug = ?", (slug,))
    conn.execute("DELETE FROM pages_fts WHERE slug = ?", (slug,))
    conn.execute("DELETE FROM links WHERE src = ?", (slug,))

    conn.execute(
        "INSERT INTO pages(slug, title, body, mtime, updated_at) VALUES (?,?,?,?,?)",
        (slug, title, body, mtime, _now_iso()),
    )
    conn.execute(
        "INSERT INTO pages_fts(slug, title, body) VALUES (?,?,?)",
        (slug, title, body),
    )
    for dst in extract_links(body):
        conn.execute("INSERT INTO links(src, dst) VALUES (?,?)", (slug, dst))


def rebuild_index(paths: DataPaths) -> int:
    """Fully rebuild the derived index from the md files. Returns page count."""
    conn = _connect(paths)
    try:
        conn.executescript(
            "DROP TABLE IF EXISTS pages;"
            "DROP TABLE IF EXISTS links;"
            "DROP TABLE IF EXISTS pages_fts;"
        )
        _create_schema(conn)
        count = 0
        if paths.wiki_dir.exists():
            for path in sorted(paths.wiki_dir.glob("*.md")):
                _index_page(conn, path.stem, path)
                count += 1
        conn.commit()
        return count
    finally:
        conn.close()


def _index_is_current(paths: DataPaths) -> bool:
    """True when the index's page set and mtimes match the md files on disk."""
    if not paths.wiki_index_db.exists():
        return False
    md_files = {p.stem: p.stat().st_mtime for p in paths.wiki_dir.glob("*.md")} \
        if paths.wiki_dir.exists() else {}
    conn = _connect(paths)
    try:
        try:
            rows = conn.execute("SELECT slug, mtime FROM pages").fetchall()
        except sqlite3.OperationalError:
            return False
        indexed = {r["slug"]: r["mtime"] for r in rows}
    finally:
        conn.close()
    if set(md_files) != set(indexed):
        return False
    for slug, mtime in md_files.items():
        # Float mtime equality with a small tolerance for filesystem rounding.
        if abs((indexed.get(slug) or 0) - mtime) > 1e-6:
            return False
    return True


def ensure_index(paths: DataPaths) -> bool:
    """Rebuild the index if it is missing or stale. Returns True if rebuilt."""
    if _index_is_current(paths):
        return False
    rebuild_index(paths)
    return True


# --------------------------------------------------------------------------- #
# Git commit of wiki md (follows the soul.py pattern)
# --------------------------------------------------------------------------- #
def _git(paths: DataPaths, *args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(paths.root), *args],
        capture_output=True,
        text=True,
        check=check,
    )


def _commit_page(paths: DataPaths, slug: str, message: str) -> str | None:
    """Stage and commit a single wiki page. Returns the commit hash or None."""
    rel = f"wiki/{slug}.md"
    _git(paths, "add", rel)
    commit = _git(paths, "commit", "-q", "-m", message)
    if commit.returncode != 0:
        commit = _git(paths, "commit", "-q", "-m", message)
        if commit.returncode != 0:
            return None
    head = _git(paths, "rev-parse", "HEAD")
    return head.stdout.strip() or None if head.returncode == 0 else None


# --------------------------------------------------------------------------- #
# Public CRUD + query API
# --------------------------------------------------------------------------- #
def write_page(
    paths: DataPaths,
    slug: str,
    content: str,
    *,
    title: str | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Create or update a wiki page from ``content`` (its markdown body).

    Frontmatter (title + created/updated timestamps) is managed here; ``[[link]]``
    targets in the body are indexed automatically. The md file is committed to
    the data repo (spec P3.5) unless ``commit`` is False. Returns page metadata.
    """
    slug = slugify(slug)
    paths.wiki_dir.mkdir(parents=True, exist_ok=True)
    path = paths.wiki_file(slug)

    existing_fm: dict[str, str] = {}
    if path.exists():
        existing_fm, _ = parse_page(path.read_text(encoding="utf-8"))

    fm, body_only = parse_page(content)
    # Body may itself carry frontmatter if the agent wrote a full doc; prefer it.
    merged_fm = {**existing_fm, **fm}
    resolved_title = title or merged_fm.get("title") or _derive_title(slug, body_only, merged_fm)
    now = _now_iso()
    merged_fm["title"] = resolved_title
    merged_fm.setdefault("created", now)
    merged_fm["updated"] = now

    path.write_text(render_page(merged_fm, body_only), encoding="utf-8")

    # Update the derived index incrementally.
    conn = _connect(paths)
    try:
        _create_schema(conn)
        _index_page(conn, slug, path)
        conn.commit()
    finally:
        conn.close()

    commit_hash = None
    if commit:
        commit_hash = _commit_page(paths, slug, f"wiki: update {slug}")

    return {
        "slug": slug,
        "title": resolved_title,
        "links": extract_links(body_only),
        "commit": commit_hash,
    }


def read_page(paths: DataPaths, slug: str) -> dict[str, Any] | None:
    """Return a page's title, body, outgoing links, and backlinks — or None."""
    slug = slugify(slug)
    path = paths.wiki_file(slug)
    if not path.exists():
        return None
    fm, body = parse_page(path.read_text(encoding="utf-8"))
    return {
        "slug": slug,
        "title": _derive_title(slug, body, fm),
        "frontmatter": fm,
        "body": body,
        "links": extract_links(body),
        "backlinks": backlinks(paths, slug),
    }


def list_pages(paths: DataPaths) -> list[dict[str, str]]:
    """List all pages as ``{slug, title}`` (from the md files, sorted by slug)."""
    out: list[dict[str, str]] = []
    if not paths.wiki_dir.exists():
        return out
    for path in sorted(paths.wiki_dir.glob("*.md")):
        fm, body = parse_page(path.read_text(encoding="utf-8"))
        out.append({"slug": path.stem, "title": _derive_title(path.stem, body, fm)})
    return out


def search(paths: DataPaths, query: str, *, limit: int = 10,
          snippet_len: int = 200) -> list[dict[str, Any]]:
    """Full-text search over pages via FTS5. Returns ``{slug, title, snippet}``."""
    ensure_index(paths)
    if not (query or "").strip():
        return []
    conn = _connect(paths)
    try:
        try:
            rows = conn.execute(
                """
                SELECT slug, title,
                       snippet(pages_fts, 2, '[', ']', ' ... ', ?) AS snip
                FROM pages_fts
                WHERE pages_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (max(1, snippet_len // 10), _fts_query(query), limit),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [
            {"slug": r["slug"], "title": r["title"], "snippet": r["snip"]}
            for r in rows
        ]
    finally:
        conn.close()


def _fts_query(query: str) -> str:
    """Sanitize a user query into a safe FTS5 MATCH expression.

    Bare words are ORed together after stripping FTS operator characters, so an
    arbitrary agent query never raises a syntax error.
    """
    tokens = re.findall(r"[A-Za-z0-9_]+", query)
    if not tokens:
        return '""'
    return " OR ".join(tokens)


def backlinks(paths: DataPaths, slug: str) -> list[str]:
    """Return the slugs of pages that link TO ``slug`` (via the index)."""
    ensure_index(paths)
    slug = slugify(slug)
    conn = _connect(paths)
    try:
        try:
            rows = conn.execute(
                "SELECT DISTINCT src FROM links WHERE dst = ? ORDER BY src",
                (slug,),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [r["src"] for r in rows]
    finally:
        conn.close()
