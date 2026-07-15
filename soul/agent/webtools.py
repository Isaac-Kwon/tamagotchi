"""Web tools: DuckDuckGo search, page reading, arXiv search (spec P3/P9 M4).

Three dependency-free (beyond ``httpx``) tools the ``web_explore`` action can
call during its tool-use loop:

    * :func:`web_search` -- POSTs a query to DuckDuckGo's no-JS HTML endpoint
      (``html.duckduckgo.com/html``) and scrapes titles/URLs/snippets with the
      stdlib ``html.parser`` (no BeautifulSoup). DuckDuckGo wraps result links
      in a redirect (``//duckduckgo.com/l/?uddg=<real-url>``); the ``uddg``
      query parameter is decoded back to the real URL.
    * :func:`web_read` -- fetches a URL with a byte cap (``max_page_kb``,
      default 500KB) and a time cap (``http_timeout_seconds``, default 20s),
      then extracts readable text (script/style/nav dropped, whitespace
      collapsed) plus the page ``<title>``.
    * :func:`arxiv_search` -- queries the arXiv Atom API
      (``export.arxiv.org/api/query``) and parses entries with
      ``xml.etree.ElementTree``.

Spec P3 explicitly rules out a domain blocklist ("안전: 도메인 차단 목록 없음
(중립성)") -- the only safety limits are size and time caps; the agent's
choice of search terms and URLs is otherwise unconstrained.

All three functions accept an optional ``client: httpx.Client`` for
dependency injection (tests pass one backed by ``httpx.MockTransport`` so no
real network call is made) and an optional ``timeout`` override. When no
client is injected, a short-lived ``httpx.Client`` is created and closed
per call.
"""

from __future__ import annotations

import urllib.parse
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from typing import Any

import httpx

# Defaults mirror config.json's ``web_actions`` section (spec P6):
#   {"enabled": true, "http_timeout_seconds": 20, "max_page_kb": 500}
DEFAULT_TIMEOUT_SECONDS: float = 20.0
DEFAULT_MAX_PAGE_KB: int = 500

DDG_HTML_URL = "https://html.duckduckgo.com/html/"
ARXIV_API_URL = "http://export.arxiv.org/api/query"
ATOM_NS = "{http://www.w3.org/2005/Atom}"

# A realistic browser-like header set. DuckDuckGo's HTML endpoint returns a
# bot-detection challenge page (HTTP 202, "anomaly.js") to bare/minimal UAs;
# a full browser-like Accept/Accept-Language/Referer set avoids that in
# practice (verified against the live endpoint). Costs nothing for the
# arXiv/page fetches either.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://html.duckduckgo.com/html/",
}


def _collapse_whitespace(text: str) -> str:
    return " ".join(text.split())


def _make_client(client: httpx.Client | None, timeout: float) -> tuple[httpx.Client, bool]:
    """Return ``(client, owns_it)``. Builds a short-lived client if none given."""
    if client is not None:
        return client, False
    return httpx.Client(timeout=timeout, headers=_HEADERS, follow_redirects=True), True


# --------------------------------------------------------------------------- #
# web_search -- DuckDuckGo HTML endpoint
# --------------------------------------------------------------------------- #
def _decode_ddg_href(href: str) -> str:
    """Decode DuckDuckGo's redirect link (``/l/?uddg=<url-encoded-real-url>``).

    Falls back to the raw ``href`` (with a protocol-relative prefix fixed up)
    when there is no ``uddg`` parameter, e.g. for already-absolute links.
    """
    if not href:
        return href
    if href.startswith("//"):
        href = "https:" + href
    parsed = urllib.parse.urlparse(href)
    qs = urllib.parse.parse_qs(parsed.query)
    uddg = qs.get("uddg")
    if uddg:
        return uddg[0]
    return href


class _DuckDuckGoResultParser(HTMLParser):
    """Extracts ``(title, url, snippet)`` triples from DDG's result HTML.

    DuckDuckGo's no-JS HTML result markup (subject to change, but stable in
    practice) looks like::

        <a class="result__a" href="//duckduckgo.com/l/?uddg=...">Title</a>
        <a class="result__snippet" href="...">Snippet text</a>

    We track which anchor class we're currently inside and accumulate text
    data into the matching field of the most recent result.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._mode: str | None = None  # "title" | "snippet" | None

    @staticmethod
    def _classes(attrs: list[tuple[str, str | None]]) -> list[str]:
        for key, value in attrs:
            if key == "class" and value:
                return value.split()
        return []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        classes = self._classes(attrs)
        href = dict(attrs).get("href") or ""
        if "result__a" in classes:
            self.results.append({"title": "", "url": _decode_ddg_href(href), "snippet": ""})
            self._mode = "title"
        elif "result__snippet" in classes:
            if not self.results:
                # Defensive: a snippet without a preceding title anchor.
                self.results.append({"title": "", "url": "", "snippet": ""})
            self._mode = "snippet"

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._mode = None

    def handle_data(self, data: str) -> None:
        if self._mode is not None and self.results:
            self.results[-1][self._mode] += data


def web_search(
    query: str,
    max_results: int = 5,
    *,
    timeout: float | None = None,
    client: httpx.Client | None = None,
) -> list[dict]:
    """Search DuckDuckGo's HTML endpoint, no API key required (spec P3).

    Returns up to ``max_results`` dicts: ``{"title", "url", "snippet"}``.
    """
    resolved_timeout = timeout if timeout is not None else DEFAULT_TIMEOUT_SECONDS
    http_client, owns_client = _make_client(client, resolved_timeout)
    try:
        resp = http_client.post(DDG_HTML_URL, data={"q": query})
        resp.raise_for_status()
        html_text = resp.text
    finally:
        if owns_client:
            http_client.close()

    parser = _DuckDuckGoResultParser()
    parser.feed(html_text)
    parser.close()

    results: list[dict] = []
    for raw in parser.results[:max_results]:
        results.append(
            {
                "title": _collapse_whitespace(raw["title"]),
                "url": raw["url"],
                "snippet": _collapse_whitespace(raw["snippet"]),
            }
        )
    return results


# --------------------------------------------------------------------------- #
# web_read -- fetch + extract readable text, with size/time caps
# --------------------------------------------------------------------------- #
class _ReadableTextParser(HTMLParser):
    """Extracts a page ``<title>`` and body text, dropping script/style/nav.

    Whitespace (including block-level line breaks) is collapsed to single
    spaces -- this is a "readable text dump" for an LLM prompt, not a layout
    preserving extractor.
    """

    SKIP_TAGS = {"script", "style", "nav"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._title_parts: list[str] = []
        self._text_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # Self-closing tags (e.g. <script src="..."/>) never carry text, so
        # there is nothing to skip/collect -- no-op deliberately.
        pass

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
        elif self._skip_depth == 0:
            self._text_parts.append(data)

    @property
    def title(self) -> str:
        return _collapse_whitespace("".join(self._title_parts))

    @property
    def text(self) -> str:
        return _collapse_whitespace("".join(self._text_parts))


def web_read(
    url: str,
    max_kb: int | None = None,
    *,
    timeout: float | None = None,
    client: httpx.Client | None = None,
) -> dict:
    """Fetch ``url`` and extract readable text (spec P3).

    Reading stops once ``max_kb`` kilobytes (default 500) have been received;
    ``truncated`` is set to ``True`` whenever the page was cut short. The
    request itself is bounded by ``timeout`` seconds (default 20).

    Returns ``{"url", "title", "text", "truncated"}``.
    """
    cap_kb = max_kb if max_kb is not None else DEFAULT_MAX_PAGE_KB
    limit_bytes = max(cap_kb, 0) * 1024
    resolved_timeout = timeout if timeout is not None else DEFAULT_TIMEOUT_SECONDS
    http_client, owns_client = _make_client(client, resolved_timeout)

    try:
        with http_client.stream("GET", url) as resp:
            resp.raise_for_status()
            body = bytearray()
            truncated = False
            for chunk in resp.iter_bytes():
                if not chunk:
                    continue
                remaining = limit_bytes - len(body)
                if remaining <= 0:
                    truncated = True
                    break
                if len(chunk) > remaining:
                    body.extend(chunk[:remaining])
                    truncated = True
                    break
                body.extend(chunk)
            encoding = resp.encoding or "utf-8"
            final_url = str(resp.url)
    finally:
        if owns_client:
            http_client.close()

    html_text = bytes(body).decode(encoding, errors="replace")
    parser = _ReadableTextParser()
    parser.feed(html_text)
    parser.close()

    return {
        "url": final_url,
        "title": parser.title,
        "text": parser.text,
        "truncated": truncated,
    }


# --------------------------------------------------------------------------- #
# arxiv_search -- arXiv Atom API
# --------------------------------------------------------------------------- #
def _entry_link(entry: ET.Element) -> str:
    """Prefer the human-readable "alternate" link; fall back to the id URL."""
    for link_el in entry.findall(f"{ATOM_NS}link"):
        if link_el.get("rel") == "alternate":
            href = link_el.get("href")
            if href:
                return href
    for link_el in entry.findall(f"{ATOM_NS}link"):
        href = link_el.get("href")
        if href:
            return href
    return (entry.findtext(f"{ATOM_NS}id") or "").strip()


def arxiv_search(
    query: str,
    max_results: int = 5,
    *,
    timeout: float | None = None,
    client: httpx.Client | None = None,
) -> list[dict]:
    """Search arXiv's Atom API (spec P3).

    Returns up to ``max_results`` dicts: ``{"title", "authors", "summary",
    "url", "published"}``.
    """
    resolved_timeout = timeout if timeout is not None else DEFAULT_TIMEOUT_SECONDS
    http_client, owns_client = _make_client(client, resolved_timeout)
    try:
        resp = http_client.get(
            ARXIV_API_URL,
            params={
                "search_query": f"all:{query}",
                "start": 0,
                "max_results": max_results,
            },
        )
        resp.raise_for_status()
        xml_text = resp.text
    finally:
        if owns_client:
            http_client.close()

    root = ET.fromstring(xml_text)
    results: list[dict] = []
    for entry in root.findall(f"{ATOM_NS}entry"):
        title = _collapse_whitespace(entry.findtext(f"{ATOM_NS}title") or "")
        summary = _collapse_whitespace(entry.findtext(f"{ATOM_NS}summary") or "")
        published = (entry.findtext(f"{ATOM_NS}published") or "").strip()
        authors = [
            _collapse_whitespace(author.findtext(f"{ATOM_NS}name") or "")
            for author in entry.findall(f"{ATOM_NS}author")
        ]
        results.append(
            {
                "title": title,
                "authors": [a for a in authors if a],
                "summary": summary,
                "url": _entry_link(entry),
                "published": published,
            }
        )
        if len(results) >= max_results:
            break
    return results
