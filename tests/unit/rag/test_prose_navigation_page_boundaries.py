"""Prose navigation links stay within a page when pages share or lack a URL."""

from opencrane.config import OpenCraneConfig
from opencrane.rag.chunker import _annotate_prose_navigation
from opencrane.shared.models.chunk import Chunk


def _prose(chunk_id, content, url, preceding=()):
    metadata = {"source_url": url} if url else {}
    chunk = Chunk(chunk_id=chunk_id, content=content, source_file="f", chunk_type="prose",
                  metadata=metadata, token_count=1)
    chunk._preceding_headings = list(preceding)
    return chunk


def test_h1_starts_a_new_page_when_pages_share_a_url():
    # A synthesized llms.txt index repeats the source's docs_url for every page.
    url = "https://docs.example.com"
    chunks = [
        _prose("a1", "# Page A\n\nIntro of A.", url),
        _prose("a2", "## 1 Alpha\n\nText.", url),
        _prose("b1", "# Page B\n\nIntro of B.", url),
    ]
    _annotate_prose_navigation(chunks, OpenCraneConfig())
    a1, a2, b1 = (c.metadata for c in chunks)
    assert a2["next_chunk_id"] is None
    assert b1["prev_chunk_id"] is None
    assert b1["position"] == 1
    assert b1["heading_path"] == "Page B"


def test_dropped_h1_starts_a_new_page_when_pages_have_no_url():
    # Pages missing from llms.txt have no source_url. Page B's title has no text
    # of its own, so it reaches the next chunk as a preceding heading.
    chunks = [
        _prose("a1", "# Page A\n\nIntro of A.", None),
        _prose("b1", "## 2 Beta\n\nText.", None, preceding=["# Page B"]),
    ]
    _annotate_prose_navigation(chunks, OpenCraneConfig())
    a1, b1 = (c.metadata for c in chunks)
    assert a1["next_chunk_id"] is None
    assert b1["prev_chunk_id"] is None
    assert b1["position"] == 1
    assert b1["heading_path"] == "Page B > 2 Beta"
