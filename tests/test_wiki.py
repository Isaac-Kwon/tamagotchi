"""Wiki tests (M3): CRUD, FTS, backlinks, and rebuild consistency (spec P3.5)."""

from __future__ import annotations

from soul.knowledge import wiki


def test_write_creates_md_and_indexes(data_paths):
    info = wiki.write_page(data_paths, "Quantum Notes", "# Quantum\n\nnotes on entanglement")
    assert info["slug"] == "quantum-notes"
    md = data_paths.wiki_file("quantum-notes")
    assert md.exists()
    text = md.read_text(encoding="utf-8")
    assert text.startswith("---")           # frontmatter present
    assert "title: Quantum" in text
    assert "entanglement" in text


def test_read_page_roundtrip(data_paths):
    wiki.write_page(data_paths, "topic-a", "# A\n\nbody about foxes")
    page = wiki.read_page(data_paths, "topic-a")
    assert page is not None
    assert page["slug"] == "topic-a"
    assert "foxes" in page["body"]
    assert wiki.read_page(data_paths, "does-not-exist") is None


def test_fts_search_hit_and_miss(data_paths):
    wiki.write_page(data_paths, "photosynthesis", "# Photosynthesis\n\nchloroplast and sunlight")
    wiki.write_page(data_paths, "cooking", "# Cooking\n\nonions and heat")
    hits = wiki.search(data_paths, "chloroplast")
    assert [h["slug"] for h in hits] == ["photosynthesis"]
    assert wiki.search(data_paths, "zzznotarealword") == []


def test_backlinks(data_paths):
    wiki.write_page(data_paths, "alpha", "# Alpha\n\nsee [[beta]] and [[gamma]]")
    wiki.write_page(data_paths, "beta", "# Beta\n\nstandalone")
    assert wiki.backlinks(data_paths, "beta") == ["alpha"]
    assert wiki.backlinks(data_paths, "gamma") == ["alpha"]
    assert wiki.backlinks(data_paths, "alpha") == []


def test_links_extracted_with_display_text(data_paths):
    info = wiki.write_page(data_paths, "src", "# Src\n\n[[target-page|nice name]]")
    assert info["links"] == ["target-page"]
    assert wiki.backlinks(data_paths, "target-page") == ["src"]


def test_manual_md_edit_then_rebuild_is_consistent(data_paths):
    wiki.write_page(data_paths, "editable", "# Editable\n\noriginal content")
    # A human/observer edits the md file directly, bypassing write_page.
    md = data_paths.wiki_file("editable")
    md.write_text(
        "---\ntitle: Editable\n---\n# Editable\n\nreplaced with tungsten and [[metal]]\n",
        encoding="utf-8",
    )
    # Also drop a brand-new page straight onto disk.
    data_paths.wiki_file("orphan").write_text(
        "# Orphan\n\ncontent about tungsten\n", encoding="utf-8"
    )

    rebuilt = wiki.rebuild_index(data_paths)
    assert rebuilt == 2

    hits = {h["slug"] for h in wiki.search(data_paths, "tungsten")}
    assert hits == {"editable", "orphan"}
    assert wiki.backlinks(data_paths, "metal") == ["editable"]


def test_ensure_index_auto_rebuilds_on_mtime_change(data_paths):
    wiki.write_page(data_paths, "drift", "# Drift\n\nseahorse")
    # Direct edit changes mtime + content; ensure_index should notice + rebuild.
    data_paths.wiki_file("drift").write_text(
        "# Drift\n\nreplaced with narwhal\n", encoding="utf-8"
    )
    assert wiki.ensure_index(data_paths) is True
    assert [h["slug"] for h in wiki.search(data_paths, "narwhal")] == ["drift"]
    # Second call: index is now current, no rebuild needed.
    assert wiki.ensure_index(data_paths) is False


def test_write_page_commits_to_data_repo(data_paths):
    info = wiki.write_page(data_paths, "committed", "# Committed\n\nbody")
    assert info["commit"]  # a real commit hash
    import subprocess

    result = subprocess.run(
        ["git", "-C", str(data_paths.root), "log", "--oneline", "--", "wiki/committed.md"],
        capture_output=True, text=True,
    )
    assert "wiki: update committed" in result.stdout
