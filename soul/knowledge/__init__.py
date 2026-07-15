"""Knowledge layer: searchable wiki (md source + derived SQLite FTS index).

The markdown pages under ``data/wiki/`` are the source of truth and are version
controlled in the data git repo. ``data/index/wiki.sqlite3`` is a *derived*
index (FTS5 + link graph) that can always be rebuilt from the md files.
"""
