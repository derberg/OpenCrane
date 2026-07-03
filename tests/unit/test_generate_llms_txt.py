"""Tests for frontmatter stripping and title derivation helpers in generate_llms_txt."""

from pathlib import Path

import pytest

from opencrane.rag.generate_llms_txt import (
    derive_title,
    filename_to_title,
    strip_frontmatter,
)


def test_process_file_is_clean_and_returns_entry(tmp_path, monkeypatch):
    # Arrange a source file + mapping so get_source_url returns a page URL.
    proj = tmp_path / "proj"
    proj.mkdir()
    f = proj / "guide.md"
    f.write_text("---\ntitle: The Guide\n---\n# The Guide\nBody text\n## Sub\nmore")
    from opencrane.rag import generate_llms_txt as g
    monkeypatch.setattr(g, "get_source_url", lambda rel, name: "https://docs.example.com/guide")
    content, entry = g.process_file(f, proj, "proj")
    assert "https://docs.example.com" not in content          # no URL injected in content
    assert content.lstrip().startswith("# The Guide")          # leading H1 == title
    assert "### https://" not in content                       # no boundary URL line
    assert entry.title == "The Guide"
    assert entry.url == "https://docs.example.com/guide"


def test_process_file_returns_none_entry_when_no_url(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    proj.mkdir()
    f = proj / "page.md"
    f.write_text("# Page\nContent")
    from opencrane.rag import generate_llms_txt as g
    monkeypatch.setattr(g, "get_source_url", lambda rel, name: None)
    content, entry = g.process_file(f, proj, "proj")
    assert entry is None
    assert content.lstrip().startswith("# Page")


def test_ensure_leading_h1_injects_when_missing():
    from opencrane.rag.generate_llms_txt import ensure_leading_h1
    assert ensure_leading_h1("no heading\nx", "T").startswith("# T\n")


def test_ensure_leading_h1_noop_when_present():
    from opencrane.rag.generate_llms_txt import ensure_leading_h1
    assert ensure_leading_h1("# T\nx", "T") == "# T\nx"


def test_build_project_output_returns_tuple(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    proj.mkdir()
    f = proj / "page.md"
    f.write_text("# Page\nContent")
    from opencrane.rag import generate_llms_txt as g
    monkeypatch.setattr(g, "get_source_url", lambda rel, name: "https://docs.example.com/page")
    result = g.build_project_output(proj, "proj")
    assert isinstance(result, tuple)
    content, entries = result
    assert isinstance(content, str)
    assert isinstance(entries, list)
    assert len(entries) == 1
    assert entries[0].title == "Page"
    assert entries[0].url == "https://docs.example.com/page"


def test_strip_frontmatter_parses_and_removes():
    text = "---\ntitle: My Page\ntags: [a, b]\n---\n# Body\ncontent"
    fm, body = strip_frontmatter(text)
    assert fm["title"] == "My Page"
    assert body == "# Body\ncontent"


def test_strip_frontmatter_absent():
    fm, body = strip_frontmatter("# No frontmatter\nx")
    assert fm == {}
    assert body == "# No frontmatter\nx"


def test_filename_to_title():
    assert filename_to_title("getting-started") == "Getting Started"
    assert filename_to_title("api_v2") == "Api V2"


def test_derive_title_prefers_frontmatter():
    assert derive_title({"title": "FM Title"}, "# Body H1\n", Path("x/file.md")) == "FM Title"


def test_derive_title_falls_back_to_first_heading():
    assert derive_title({}, "## Sub First\n", Path("x/file.md")) == "Sub First"


def test_derive_title_falls_back_to_filename():
    assert derive_title({}, "no headings here", Path("x/getting-started.md")) == "Getting Started"
