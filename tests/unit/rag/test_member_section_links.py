"""List items and table rows record their section (parent_chunk_id) and doc_order."""

import json
from pathlib import Path

from opencrane.config import OpenCraneConfig
from opencrane.rag.chunker import _annotate_prose_navigation, main
from opencrane.shared.models.chunk import Chunk

PAGE = Path(__file__).resolve().parents[2] / "fixtures" / "get_section_output" / "page.md"


def _prose(chunk_id, content, url="https://d/a", preceding=()):
    chunk = Chunk(chunk_id=chunk_id, content=content, source_file="f", chunk_type="prose",
                  metadata={"source_url": url}, token_count=1)
    chunk._preceding_headings = list(preceding)
    return chunk


def _item(chunk_id, breadcrumb, url="https://d/a"):
    return Chunk(chunk_id=chunk_id, content=f"# {breadcrumb}\nItem.", source_file="f",
                 chunk_type="list_item", token_count=1, metadata={
                     "breadcrumb_path": breadcrumb, "list_id": "L", "list_style": "unordered",
                     "position": 1, "total_siblings": 1, "sibling_ids": [], "sibling_previews": [],
                     "parent_item_id": None, "depth": 0, "source_url": url})


def test_members_link_to_their_section_and_count_doc_order():
    chunks = [
        _prose("top", "# Page\n\nIntro."),
        _prose("a", "## A\n\nText of A.\n\n### A inner\n\nInner text."),
        _item("in-a", "Page > A"),
        _item("in-inner", "Page > A > A inner"),
        # "## B" has only a list, so the prose chunker dropped the heading.
        _item("in-b", "Page > B"),
        _prose("c", "## C\n\nText of C.", preceding=["## B"]),
        _item("other-page", "Other > X", url="https://d/b"),
        _prose("other", "# Other\n\nText.", url="https://d/b"),
    ]
    _annotate_prose_navigation(chunks, OpenCraneConfig())
    meta = {c.chunk_id: c.metadata for c in chunks}

    assert meta["in-a"]["parent_chunk_id"] == "a"
    assert meta["in-inner"]["parent_chunk_id"] == "a"
    assert meta["in-b"]["parent_chunk_id"] == "top"
    # A list on a page the heading stack has not reached yet has no section.
    assert meta["other-page"]["parent_chunk_id"] is None
    assert [meta[c]["doc_order"] for c in ("top", "a", "in-a", "in-inner", "in-b", "c")] == [1, 2, 3, 4, 5, 6]
    assert [meta[c]["doc_order"] for c in ("other-page", "other")] == [1, 2]
    for c in chunks:
        Chunk(**c.model_dump())


def test_chunked_page_links_lists_and_table_to_sections(tmp_path, monkeypatch):
    llms = tmp_path / "llmstxt"
    llms.mkdir()
    (llms / "llms-full.txt").write_text(PAGE.read_text())
    (llms / "llms.txt").write_text("# Docs\n## gateway-docs\n- [Gateway operations](https://docs.example.com/gateway/operations)\n")
    out = tmp_path / "chunks.json"
    monkeypatch.chdir(tmp_path)
    main(llmstxt_dir=llms, chunks_file=out)
    chunks = json.loads(out.read_text())

    def prose_id(start):
        return next(c["chunk_id"] for c in chunks if c["chunk_type"] == "prose" and c["content"].startswith(start))

    parents = {
        c["content"].split("\n")[1]: c["metadata"]["parent_chunk_id"]
        for c in chunks if c["chunk_type"] in ("list_item", "table_row")
    }
    upgrade, log_settings = prose_id("## Upgrade the gateway"), prose_id("### Log settings")
    assert parents["Helm in version 3.14 or later."] == upgrade
    assert parents["2. Install the gateway Helm chart in version 1.7.0."] == upgrade
    assert parents["The gateway reads these environment variables at startup:"] == log_settings
    # "Rollback checks" has only a list, so the list hangs off the enclosing section.
    assert parents["Check that the user sessions recover within two minutes."] == upgrade

    in_order = sorted(chunks, key=lambda c: c["metadata"]["doc_order"])
    assert [c["content"].split("\n")[-1][:20] for c in in_order][:5] == [
        "The gateway routes u",
        "Before you start, ch",
        "A Kubernetes cluster",
        "Helm in version 3.14",
        "To upgrade the gatew",
    ]
