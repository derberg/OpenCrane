"""Tests for LlmsIndex.parse and the ordered, source-scoped page-join consumer."""

from opencrane.rag.services.llms_index import LlmsIndex


INDEX = """# Docs
## src-a
- [Home](https://x/home)
- [Setup](https://x/setup)
## src-b
- [Home](https://y/home)
"""


def test_parse_orders_and_scopes():
    idx = LlmsIndex.parse(INDEX)
    assert idx.sources() == ["src-a", "src-b"]
    assert [e.title for e in idx.entries_for("src-a")] == ["Home", "Setup"]
    assert [e.title for e in idx.entries_for("src-b")] == ["Home"]


def test_parse_links_before_any_section_use_empty_section():
    idx = LlmsIndex.parse("# Docs\n- [Loose](https://x/loose)\n## real\n- [Home](https://x/home)\n")
    assert idx.sources() == ["", "real"]
    assert [e.title for e in idx.entries_for("")] == ["Loose"]
    assert idx.entries_for("real")[0].url == "https://x/home"


def test_entries_for_unknown_source_is_empty():
    idx = LlmsIndex.parse(INDEX)
    assert idx.entries_for("missing") == []


def test_parse_ignores_blank_lines():
    idx = LlmsIndex.parse("# Docs\n\n## s\n\n- [Home](https://x/home)\n\n")
    assert idx.sources() == ["s"]
    assert idx.entries_for("s")[0].url == "https://x/home"


def test_match_page_positional():
    idx = LlmsIndex.parse(INDEX)
    url, cur = idx.match_page("src-a", "Home", 0)
    assert url == "https://x/home" and cur == 1
    url, cur = idx.match_page("src-a", "Setup", cur)
    assert url == "https://x/setup" and cur == 2


def test_match_page_realigns_on_drift():
    idx = LlmsIndex.parse(INDEX)
    url, cur = idx.match_page("src-a", "Setup", 0)  # skipped 'Home'
    assert url == "https://x/setup" and cur == 2


def test_match_page_no_match_returns_none():
    idx = LlmsIndex.parse(INDEX)
    url, cur = idx.match_page("src-a", "Ghost", 0)
    assert url is None and cur == 0


def test_match_page_case_insensitive_and_whitespace_normalized():
    idx = LlmsIndex.parse(INDEX)
    url, cur = idx.match_page("src-a", "  home  ", 0)
    assert url == "https://x/home" and cur == 1
    url, cur = idx.match_page("src-a", "SET   UP", cur)
    # 'Setup' has no internal space, so normalized 'SET UP' won't equal 'setup'
    assert url is None and cur == 1


def test_match_page_cursor_at_end_returns_none():
    idx = LlmsIndex.parse(INDEX)
    url, cur = idx.match_page("src-a", "Home", 2)
    assert url is None and cur == 2


def test_match_page_unknown_source_returns_none():
    idx = LlmsIndex.parse(INDEX)
    url, cur = idx.match_page("nope", "Home", 0)
    assert url is None and cur == 0
