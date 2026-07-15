"""Tests for web tools: DuckDuckGo search, page reading, arXiv search (M4).

Everything runs against ``httpx.MockTransport`` with canned HTML/Atom
fixtures -- no real network call is made (spec P10: "MockTransport로 DDG
HTML/arXiv Atom 고정 응답 파싱 검증").
"""

from __future__ import annotations

import urllib.parse

import httpx
import pytest

from soul.agent.webtools import (
    DEFAULT_MAX_PAGE_KB,
    arxiv_search,
    web_read,
    web_search,
)

# --------------------------------------------------------------------------- #
# Fixtures: canned responses
# --------------------------------------------------------------------------- #
DDG_HTML = """
<!DOCTYPE html>
<html>
<body>
<div class="results">
  <div class="result results_links results_links_deep web-result">
    <div class="links_main links_deep result__body">
      <h2 class="result__title">
        <a rel="nofollow" class="result__a"
           href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fen.wikipedia.org%2Fwiki%2FPython&amp;rut=abc">
          The <b>Python</b> Programming Language
        </a>
      </h2>
      <a class="result__snippet" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fen.wikipedia.org%2Fwiki%2FPython">
        Python is a <b>high-level</b>, general-purpose programming language.
      </a>
    </div>
  </div>
  <div class="result results_links results_links_deep web-result">
    <div class="links_main links_deep result__body">
      <h2 class="result__title">
        <a rel="nofollow" class="result__a"
           href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.python.org%2F3%2F&amp;rut=def">
          Python Docs
        </a>
      </h2>
      <a class="result__snippet" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.python.org%2F3%2F">
        Official documentation for the Python language.
      </a>
    </div>
  </div>
  <div class="result results_links results_links_deep web-result">
    <div class="links_main links_deep result__body">
      <h2 class="result__title">
        <a rel="nofollow" class="result__a"
           href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fthird&amp;rut=ghi">
          Third Result
        </a>
      </h2>
      <a class="result__snippet" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fthird">
        A third, lower-ranked result that should be excluded by max_results.
      </a>
    </div>
  </div>
</div>
</body>
</html>
"""

ARXIV_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>ArXiv Query</title>
  <entry>
    <id>http://arxiv.org/abs/1234.5678v1</id>
    <updated>2024-01-02T00:00:00Z</updated>
    <published>2024-01-01T00:00:00Z</published>
    <title>
      Attention Is All You Need Again
    </title>
    <summary>
      We propose a new architecture
      that improves on the original transformer.
    </summary>
    <author><name>Jane Doe</name></author>
    <author><name>John Smith</name></author>
    <link href="http://arxiv.org/abs/1234.5678v1" rel="alternate" type="text/html"/>
    <link title="pdf" href="http://arxiv.org/pdf/1234.5678v1" rel="related" type="application/pdf"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/8765.4321v2</id>
    <published>2024-02-01T00:00:00Z</published>
    <title>A Second Paper</title>
    <summary>Another abstract.</summary>
    <author><name>Ada Lovelace</name></author>
    <link href="http://arxiv.org/abs/8765.4321v2" rel="alternate" type="text/html"/>
  </entry>
</feed>
"""

READ_HTML = """
<html>
<head>
  <title>  Example Page Title  </title>
  <style>body { color: red; }</style>
  <script>console.log("should be dropped");</script>
</head>
<body>
  <nav>Home | About | Contact</nav>
  <h1>Welcome</h1>
  <p>This is the
  first paragraph of readable text.</p>
  <p>This is the second paragraph.</p>
</body>
</html>
"""


def _client_for(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# --------------------------------------------------------------------------- #
# web_search
# --------------------------------------------------------------------------- #
def test_web_search_parses_title_url_snippet():
    def handler(request):
        assert request.method == "POST"
        return httpx.Response(200, text=DDG_HTML)

    results = web_search("python", max_results=5, client=_client_for(handler))

    assert len(results) == 3
    first = results[0]
    assert first["title"] == "The Python Programming Language"
    assert first["url"] == "https://en.wikipedia.org/wiki/Python"
    assert "high-level" in first["snippet"]
    assert set(first) == {"title", "url", "snippet"}


def test_web_search_respects_max_results():
    def handler(request):
        return httpx.Response(200, text=DDG_HTML)

    results = web_search("python", max_results=2, client=_client_for(handler))
    assert len(results) == 2
    assert results[1]["url"] == "https://docs.python.org/3/"


def test_web_search_decodes_uddg_redirect_url():
    def handler(request):
        return httpx.Response(200, text=DDG_HTML)

    results = web_search("python", client=_client_for(handler))
    for r in results:
        # No result should still be pointing at the DDG redirect endpoint.
        assert "duckduckgo.com/l/" not in r["url"]
        assert r["url"].startswith("https://")


def test_web_search_sends_query_to_ddg_html_endpoint():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["body"] = request.read().decode("utf-8")
        return httpx.Response(200, text="<html><body><div class='results'></div></body></html>")

    web_search("soul tamagotchi agent", client=_client_for(handler))
    assert "html.duckduckgo.com" in captured["url"]
    parsed_body = urllib.parse.parse_qs(captured["body"])
    assert parsed_body["q"] == ["soul tamagotchi agent"]


def test_web_search_empty_results_when_no_matches():
    def handler(request):
        return httpx.Response(200, text="<html><body>No results.</body></html>")

    results = web_search("gibberish query", client=_client_for(handler))
    assert results == []


# --------------------------------------------------------------------------- #
# web_read
# --------------------------------------------------------------------------- #
def test_web_read_extracts_title_and_text_dropping_script_style_nav():
    def handler(request):
        return httpx.Response(200, text=READ_HTML)

    result = web_read("https://example.com/page", client=_client_for(handler))

    assert result["url"] == "https://example.com/page"
    assert result["title"] == "Example Page Title"
    assert "Welcome" in result["text"]
    assert "first paragraph of readable text" in result["text"]
    assert "second paragraph" in result["text"]
    assert "should be dropped" not in result["text"]  # script
    assert "color: red" not in result["text"]  # style
    assert "Home | About | Contact" not in result["text"]  # nav
    assert result["truncated"] is False


def test_web_read_collapses_whitespace():
    def handler(request):
        return httpx.Response(200, text=READ_HTML)

    result = web_read("https://example.com/page", client=_client_for(handler))
    assert "\n" not in result["text"]
    assert "  " not in result["text"]


def test_web_read_truncates_at_size_cap():
    big_body = "<html><body><p>" + ("word " * 5000) + "</p></body></html>"

    def handler(request):
        return httpx.Response(200, text=big_body)

    # Cap far below the full body size (body is tens of KB).
    result = web_read("https://example.com/big", max_kb=1, client=_client_for(handler))

    assert result["truncated"] is True
    # Should not have decoded/kept the entire multi-KB body as text.
    assert len(result["text"]) < len(big_body)


def test_web_read_default_cap_used_when_max_kb_not_given():
    def handler(request):
        return httpx.Response(200, text=READ_HTML)

    # Just confirms the default constant is what P6 specifies (500KB) and
    # that a small page under that cap is never marked truncated.
    assert DEFAULT_MAX_PAGE_KB == 500
    result = web_read("https://example.com/page", client=_client_for(handler))
    assert result["truncated"] is False


def test_web_read_small_cap_on_small_page_is_not_falsely_truncated():
    def handler(request):
        return httpx.Response(200, text="<html><body><p>hi</p></body></html>")

    result = web_read("https://example.com/tiny", max_kb=500, client=_client_for(handler))
    assert result["truncated"] is False


def test_web_read_raises_on_http_error_status():
    def handler(request):
        return httpx.Response(404, text="not found")

    with pytest.raises(httpx.HTTPStatusError):
        web_read("https://example.com/missing", client=_client_for(handler))


def test_web_read_timeout_propagates():
    def handler(request):
        raise httpx.TimeoutException("timed out", request=request)

    with pytest.raises(httpx.TimeoutException):
        web_read("https://example.com/slow", client=_client_for(handler))


# --------------------------------------------------------------------------- #
# arxiv_search
# --------------------------------------------------------------------------- #
def test_arxiv_search_parses_entries():
    def handler(request):
        assert "export.arxiv.org/api/query" in str(request.url)
        return httpx.Response(200, text=ARXIV_ATOM)

    results = arxiv_search("transformers", client=_client_for(handler))

    assert len(results) == 2
    first = results[0]
    assert first["title"] == "Attention Is All You Need Again"
    assert first["authors"] == ["Jane Doe", "John Smith"]
    assert "new architecture" in first["summary"]
    assert first["url"] == "http://arxiv.org/abs/1234.5678v1"
    assert first["published"] == "2024-01-01T00:00:00Z"
    assert set(first) == {"title", "authors", "summary", "url", "published"}


def test_arxiv_search_respects_max_results():
    def handler(request):
        return httpx.Response(200, text=ARXIV_ATOM)

    results = arxiv_search("transformers", max_results=1, client=_client_for(handler))
    assert len(results) == 1
    assert results[0]["title"] == "Attention Is All You Need Again"


def test_arxiv_search_query_encoded_in_request():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(200, text=ARXIV_ATOM)

    arxiv_search("quantum computing", client=_client_for(handler))
    query = urllib.parse.parse_qs(urllib.parse.urlparse(captured["url"]).query)
    assert query["search_query"] == ["all:quantum computing"]


def test_arxiv_search_empty_feed_returns_empty_list():
    empty_feed = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom"><title>ArXiv Query</title></feed>"""

    def handler(request):
        return httpx.Response(200, text=empty_feed)

    results = arxiv_search("nothing matches this", client=_client_for(handler))
    assert results == []


def test_arxiv_search_timeout_propagates():
    def handler(request):
        raise httpx.TimeoutException("timed out", request=request)

    with pytest.raises(httpx.TimeoutException):
        arxiv_search("slow query", client=_client_for(handler))
