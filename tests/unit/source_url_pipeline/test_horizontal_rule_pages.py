"""Regression test: markdown thematic breaks (horizontal rules) must not split pages.

A markdown thematic break / horizontal rule (``---``, ``----``, ``-----`` — any
blank-line-surrounded run of 3+ dashes) is a legitimate content construct, not a
page boundary.  The generator separates pages with a collision-proof sentinel
comment (``<!-- opencrane:page -->``) precisely because a dash-based separator is
indistinguishable from an HR.  The chunker must therefore split pages ONLY on the
sentinel, never on a dash run, so HRs in prose leave the page intact and every
chunk keeps its per-page ``source_url``.
"""

from __future__ import annotations

import logging

import pytest

from tests.unit.source_url_pipeline.test_multi_project_alignment import run_pipeline


@pytest.mark.unit
def test_horizontal_rules_do_not_split_pages(tmp_path, caplog):
    """A single page whose body has ``---`` and ``-----`` HRs stays one page.

    On dash-based-separator code the HRs mis-split the page: the fragments after
    each HR have no ``# H1`` → empty title → no llms.txt index match → their
    chunks lose ``source_url``.  With the sentinel separator the page is intact
    and every chunk carries the file's per-page URL.
    """
    workspace = tmp_path / "workspace"
    sources_base = workspace / ".opencrane" / "sources"
    (sources_base / "proj-a").mkdir(parents=True)
    (sources_base / "proj-a" / "glossary.md").write_text(
        "# Glossary\n\n"
        "Intro paragraph describing the glossary of terms here.\n\n"
        "First term definition with enough words to form a chunk.\n\n"
        "---\n\n"
        "Second term definition after a three-dash thematic break here.\n\n"
        "-----\n\n"
        "Third term definition after a five-dash thematic break here.\n"
    )

    config_yaml = (
        "sources:\n"
        "  proj-a:\n"
        "    url: https://github.com/example/proj-a\n"
        "    docs_url: https://a.example.com/docs\n"
        "    manual: true\n"
    )

    caplog.set_level(logging.WARNING)
    chunks, llms_full, llms_txt = run_pipeline(
        workspace, config_yaml, pytest.MonkeyPatch()
    )

    # A horizontal rule must never produce the empty-title "no index match" warning.
    assert "No llms.txt index match for page ''" not in caplog.text, (
        "A horizontal rule split the page into an empty-title fragment"
    )

    # Every chunk with content must carry the single page's URL — no None from a
    # fragment after an HR whose empty title didn't match the index.
    content_urls = {
        c.metadata.get("source_url")
        for c in chunks
        if c.content and c.content.strip()
    }
    assert content_urls == {"https://a.example.com/docs/glossary"}, (
        f"A horizontal rule mis-split the page: {content_urls}"
    )
