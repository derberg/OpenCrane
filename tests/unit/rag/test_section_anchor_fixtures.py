"""Fixture-driven validation of section anchors through the full chunk pipeline.

Runs ``opencrane chunk`` (``chunker.main``, which is where the section-anchor
pass lives) over ``tests/fixtures/section_anchors/`` and checks each chunk's
``source_url`` / ``section_anchor`` against the committed expected output. This
locks the input -> output contract in a place reviewers can read, covering the
prose (heading-from-content) and list_item (heading-from-breadcrumb) paths, the
page-title H1 skip, and the invariant that ``source_url`` stays a clean page link.
"""

import json
from pathlib import Path

import pytest

from opencrane.rag.chunker import main

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "section_anchors"


def _content(chunk) -> str:
    text = chunk.get("content")
    return text if isinstance(text, str) else ""


@pytest.mark.unit
def test_section_anchor_fixture(tmp_path, monkeypatch):
    llms_dir = tmp_path / "llmstxt"
    llms_dir.mkdir()
    (llms_dir / "llms-full.txt").write_text((FIXTURE_DIR / "llms-full.txt").read_text())
    (llms_dir / "llms.txt").write_text((FIXTURE_DIR / "llms.txt").read_text())
    out = tmp_path / "chunks.json"
    monkeypatch.setenv("AI_DOCS_LLMSTXT_DIR", str(llms_dir))
    monkeypatch.setenv("AI_DOCS_CHUNKS_FILE", str(out))

    main()

    chunks = json.loads(out.read_text())

    # Invariant: source_url is always a clean page link — the anchor lives in
    # its own section_anchor field, never appended to the URL.
    for chunk in chunks:
        assert "#" not in chunk["metadata"].get("source_url", "")

    expected = json.loads((FIXTURE_DIR / "expected_chunks.json").read_text())["chunks"]
    for entry in expected:
        marker = entry["content_contains"]
        matches = [c for c in chunks if marker in _content(c)]
        assert len(matches) == 1, f"expected exactly one chunk containing {marker!r}, got {len(matches)}"
        chunk = matches[0]
        assert chunk["chunk_type"] == entry["chunk_type"], marker
        assert chunk["metadata"].get("source_url") == entry["source_url"], marker
        assert chunk["metadata"].get("section_anchor") == entry["section_anchor"], marker
        assert chunk["metadata"].get("breadcrumb_path") == entry["breadcrumb_path"], marker
