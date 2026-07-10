"""Tests for IndexEntry model and render_llms_txt serializer."""

import pytest
from opencrane.rag.services.llms_index import IndexEntry, render_llms_txt


def test_render_llms_txt_standard_shape():
    out = render_llms_txt("Docs", [
        ("source-a", [IndexEntry("source-a", "Home", "https://x/home"),
                      IndexEntry("source-a", "Setup", "https://x/setup")]),
    ])
    assert out.splitlines()[0] == "# Docs"
    assert "## source-a" in out
    assert "- [Home](https://x/home)" in out
    assert "- [Setup](https://x/setup)" in out


def test_render_skips_empty_sections():
    out = render_llms_txt("Docs", [("empty", [])])
    assert "## empty" not in out


def test_render_multiple_sections():
    out = render_llms_txt("My Docs", [
        ("src-1", [IndexEntry("src-1", "Page A", "https://a/page-a")]),
        ("src-2", [IndexEntry("src-2", "Page B", "https://b/page-b")]),
    ])
    assert out.splitlines()[0] == "# My Docs"
    assert "## src-1" in out
    assert "## src-2" in out
    assert "- [Page A](https://a/page-a)" in out
    assert "- [Page B](https://b/page-b)" in out


def test_render_mixed_empty_and_non_empty():
    out = render_llms_txt("Docs", [
        ("empty", []),
        ("real", [IndexEntry("real", "Guide", "https://x/guide")]),
    ])
    assert "## empty" not in out
    assert "## real" in out
    assert "- [Guide](https://x/guide)" in out


def test_render_empty_sections_list():
    out = render_llms_txt("Docs", [])
    assert out.splitlines()[0] == "# Docs"
    # No sections at all — just the title line
    assert "##" not in out
