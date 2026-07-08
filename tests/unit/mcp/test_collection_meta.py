"""Tests for the collection_meta sidecar (chunk-type set persisted at index time)."""

import json

from opencrane.mcp.collection_meta import read_chunk_types, write_chunk_types


def test_write_then_read_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DOCS_COLLECTION_META_FILE", str(tmp_path / "meta.json"))
    write_chunk_types(["prose", "list_item", "prose"])  # dedupes + sorts
    assert read_chunk_types() == {"prose", "list_item"}


def test_write_creates_parent_dirs(tmp_path, monkeypatch):
    target = tmp_path / "nested" / "dir" / "meta.json"
    monkeypatch.setenv("AI_DOCS_COLLECTION_META_FILE", str(target))
    write_chunk_types(["prose"])
    assert json.loads(target.read_text())["chunk_types"] == ["prose"]


def test_read_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DOCS_COLLECTION_META_FILE", str(tmp_path / "absent.json"))
    assert read_chunk_types() == set()


def test_read_malformed_file_returns_empty(tmp_path, monkeypatch):
    path = tmp_path / "meta.json"
    path.write_text("{ not json", encoding="utf-8")
    monkeypatch.setenv("AI_DOCS_COLLECTION_META_FILE", str(path))
    assert read_chunk_types() == set()


def test_read_non_list_chunk_types_returns_empty(tmp_path, monkeypatch):
    path = tmp_path / "meta.json"
    path.write_text(json.dumps({"chunk_types": "prose"}), encoding="utf-8")
    monkeypatch.setenv("AI_DOCS_COLLECTION_META_FILE", str(path))
    assert read_chunk_types() == set()
