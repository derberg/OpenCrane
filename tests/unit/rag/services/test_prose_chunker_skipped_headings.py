"""Headings of dropped heading-only sections are handed to the next prose chunk."""

from pathlib import Path
from types import SimpleNamespace

from opencrane.rag.services.prose_chunker import ProseChunkingStrategy


def _process(text):
    node = SimpleNamespace(text=text, node_type="text", source_url="https://d/x")
    return ProseChunkingStrategy().process(node, Path("f.md"))


def test_dropped_heading_only_sections_are_carried_to_next_chunk():
    chunks = _process(
        "# Title\n\nIntro text here.\n\n"
        "## [https://d] 5 Empty clause\n\n"
        "### 5.1 T\n\nok\n\n"  # dropped too: under 15 chars of content
        "### 5.2 Real section\n\nEnough text for a real chunk.\n"
    )
    assert [c.content.split("\n")[0] for c in chunks] == ["# Title", "### 5.2 Real section"]
    assert chunks[0]._preceding_headings == []
    assert chunks[1]._preceding_headings == ["## 5 Empty clause", "### 5.1 T"]
    # Never serialized: chunk content, ids and metadata are unchanged.
    assert "_preceding_headings" not in chunks[1].model_dump()
    assert chunks[1].metadata == {"source_url": "https://d/x"}
