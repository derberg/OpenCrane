"""Regression test: Setext heading underlines must not split source blocks/pages.

Setext underlines in page content (``Title\\n======`` for H1, ``Sub\\n------``
for H2) must NOT be mistaken for the generator's ``======`` source-block or
``-----`` page separators by the chunker.  The generator always surrounds real
separators with blank lines; a Setext underline sits directly under its title.
"""

from __future__ import annotations

import logging

import pytest

from tests.unit.source_url_pipeline.test_multi_project_alignment import run_pipeline


@pytest.mark.unit
def test_setext_headings_do_not_create_phantom_blocks(tmp_path, caplog):
    """A page with Setext H1/H2 underlines stays a single page under its source.

    The chunker must not treat those underlines as ``======``/``-----``
    separators, which would create phantom blocks/pages and break the join.
    """
    workspace = tmp_path / "workspace"
    sources_base = workspace / ".opencrane" / "sources"
    (sources_base / "proj-a").mkdir(parents=True)
    (sources_base / "proj-a" / "home.md").write_text(
        "# Alpha Home\n\n"
        "Intro paragraph for the alpha home page here.\n\n"
        "Setext Title\n"
        "======\n\n"
        "Body under the setext heading with some content.\n\n"
        "Setext Sub\n"
        "------\n\n"
        "More body content under the setext subheading here.\n"
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

    assert "does not match content" not in caplog.text, (
        "Setext underline created a phantom block causing count mismatch"
    )
    # Every chunk with content must carry the single page's URL (no None from a
    # phantom page whose title didn't match the index).
    content_urls = {
        c.metadata.get("source_url")
        for c in chunks
        if c.content and c.content.strip()
    }
    assert content_urls == {"https://a.example.com/docs/home"}, (
        f"Setext underline mis-split the page: {content_urls}"
    )
