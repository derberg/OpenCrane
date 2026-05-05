"""Unit tests for SourceResolver."""

import pytest

from opencrane.rag.services.source_resolver import SourceResolver


class TestSourceResolver:
    def test_resolves_by_url_prefix(self):
        resolver = SourceResolver({
            "Org/repo-a": {"url": "https://github.com/Org/repo-a"},
            "Org/repo-b": {"url": "https://github.com/Org/repo-b"},
        })
        assert resolver.resolve("https://github.com/Org/repo-a/blob/main/docs/x.md") == "Org/repo-a"
        assert resolver.resolve("https://github.com/Org/repo-b") == "Org/repo-b"

    def test_resolves_by_docs_url_when_present(self):
        resolver = SourceResolver({
            "vendor/docs": {
                "url": "https://github.com/vendor/repo",
                "docs_url": "https://docs.vendor.com/guide",
            },
        })
        assert resolver.resolve("https://docs.vendor.com/guide/page.html") == "vendor/docs"
        assert resolver.resolve("https://github.com/vendor/repo/blob/main/x.md") == "vendor/docs"

    def test_longest_prefix_wins(self):
        resolver = SourceResolver({
            "outer": {"url": "https://github.com/Org/repo"},
            "inner": {"url": "https://github.com/Org/repo/tree/main/sub"},
        })
        assert resolver.resolve("https://github.com/Org/repo/tree/main/sub/file.md") == "inner"
        assert resolver.resolve("https://github.com/Org/repo/tree/main/other") == "outer"

    def test_returns_none_for_unmatched_or_empty_url(self):
        resolver = SourceResolver({"X": {"url": "https://x.example"}})
        assert resolver.resolve("https://other.example/path") is None
        assert resolver.resolve(None) is None
        assert resolver.resolve("") is None

    def test_skips_entries_without_urls(self):
        resolver = SourceResolver({"empty": {}})
        assert resolver.resolve("https://anything") is None
        assert resolver.known_names() == []

    def test_known_names_returns_sorted_unique_keys(self):
        resolver = SourceResolver({
            "b": {"url": "https://b.example"},
            "a": {"url": "https://a.example", "docs_url": "https://a-docs.example"},
        })
        assert resolver.known_names() == ["a", "b"]
