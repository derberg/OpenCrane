"""Tests for frontmatter stripping and title derivation helpers in generate_llms_txt."""

from pathlib import Path

import pytest

from opencrane.rag.generate_llms_txt import (
    derive_title,
    filename_to_title,
    strip_frontmatter,
)


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
