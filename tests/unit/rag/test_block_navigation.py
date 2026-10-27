"""Tests for prose navigation around chunks from declared content blocks."""

from opencrane.config import OpenCraneConfig
from opencrane.rag.chunker import _annotate_prose_navigation
from opencrane.shared.models.chunk import Chunk


def _prose(chunk_id, content, in_block=False):
    chunk = Chunk(chunk_id=chunk_id, content=content, source_file="f", chunk_type="prose",
                  metadata={"source_url": "https://d/x"}, token_count=1)
    chunk._in_block = in_block
    return chunk


def test_heading_inside_block_is_not_parent_after_block():
    a = _prose("a", "## A\n\nText A.")
    inner = _prose("inner", "### Inner\n\nInner text.", in_block=True)
    after = _prose("after", "More text after the block.")
    _annotate_prose_navigation([a, inner, after], OpenCraneConfig())
    assert inner.metadata["heading_path"] == "A > Inner"
    assert after.metadata["heading_path"] == "A"
    assert after.metadata["parent_chunk_id"] is None


def test_block_chunks_still_link_as_neighbours():
    a = _prose("a", "## A\n\nText A.")
    inner = _prose("inner", "### Inner\n\nInner text.", in_block=True)
    after = _prose("after", "More text after the block.")
    _annotate_prose_navigation([a, inner, after], OpenCraneConfig())
    assert a.metadata["next_chunk_id"] == "inner"
    assert after.metadata["prev_chunk_id"] == "inner"


def test_heading_after_block_continues_from_before_block():
    a = _prose("a", "## A\n\nText A.")
    inner = _prose("inner", "## Inner\n\nInner text.", in_block=True)
    b = _prose("b", "### B\n\nText B.")
    _annotate_prose_navigation([a, inner, b], OpenCraneConfig())
    assert b.metadata["heading_path"] == "A > B"
    assert b.metadata["parent_chunk_id"] == "a"
