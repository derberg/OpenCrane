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
    # A list above the first prose chunk of its page links to that chunk.
    assert meta["other-page"]["parent_chunk_id"] == "other"
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

    # The line after the breadcrumb, and after the list's lead-in when it has one.
    parents = {
        c["content"].split("\n")[2 if c["metadata"].get("list_caption") else 1]: c["metadata"]["parent_chunk_id"]
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


def _chunk(tmp_path, monkeypatch, md):
    """Chunk a one-page bundle titled "Page" and return its chunks."""
    llms = tmp_path / "llmstxt"
    llms.mkdir()
    (llms / "llms-full.txt").write_text(md)
    (llms / "llms.txt").write_text("# Docs\n## src\n- [Page](https://docs.example.com/p)\n")
    out = tmp_path / "chunks.json"
    monkeypatch.chdir(tmp_path)
    main(llmstxt_dir=llms, chunks_file=out)
    return json.loads(out.read_text())


def _parents(chunks):
    """``{prose start or member text: parent_chunk_id}``, with prose keyed by their first line."""
    return {
        c["content"].split("\n")[1 if c["chunk_type"] != "prose" else 0]: c["metadata"]["parent_chunk_id"]
        for c in chunks
    }


def _id(chunks, start):
    return next(c["chunk_id"] for c in chunks if c["chunk_type"] == "prose" and c["content"].startswith(start))


INTRO = "Intro paragraph with enough words to stay a chunk."


def test_list_above_the_first_prose_chunk_links_to_it(tmp_path, monkeypatch):
    # The page title has no chunk of its own, so the list sits above any prose.
    chunks = _chunk(tmp_path, monkeypatch,
                    "# Page\n\n- Fixed X\n- Added Y\n\n## Known issues\n\nSome text that is long enough here.\n")
    parents = _parents(chunks)
    assert parents["Fixed X"] == parents["Added Y"] == _id(chunks, "## Known issues")


def test_list_under_headings_without_chunks_links_to_the_prose_before_it(tmp_path, monkeypatch):
    # "Intro." is too short to keep, so neither "Page" nor the second "Setup" has a chunk.
    chunks = _chunk(tmp_path, monkeypatch, (
        "# Page\n\nIntro.\n\n## Setup\n\nFirst setup text.\n\n## Other\n\nOther text.\n\n"
        "## Setup\n\n- second setup item one\n- second setup item two\n"
    ))
    parents = _parents(chunks)
    assert parents["second setup item one"] == _id(chunks, "## Other")


def test_heading_titles_with_the_breadcrumb_separator(tmp_path, monkeypatch):
    chunks = _chunk(tmp_path, monkeypatch, "# Page\n\nIntro.\n\n## A > B heading\n\nBaz.\n\n- d\n")
    assert _parents(chunks)["d"] == _id(chunks, "## A > B heading")


def test_list_under_a_repeated_heading_skips_the_earlier_section(tmp_path, monkeypatch):
    chunks = _chunk(tmp_path, monkeypatch, (
        f"# Page\n\n{INTRO}\n\n## Example\n\nFirst example text that is long enough to be kept as prose.\n\n"
        "## Example\n\n- second example item one\n- second example item two\n"
    ))
    # The second "Example" has no chunk, so the list hangs off the page, not the first "Example".
    assert _parents(chunks)["second example item one"] == _id(chunks, "# Page")


def test_table_under_a_repeated_heading_skips_the_earlier_section(tmp_path, monkeypatch):
    chunks = _chunk(tmp_path, monkeypatch, (
        f"# Page\n\n{INTRO}\n\n## Example\n\nFirst example text that is long enough to be kept as prose.\n\n"
        "- a list item in the first example\n\n"
        "## Example\n\n| Key | Value |\n|---|---|\n| x | 1 |\n\n"
        "## Other\n\nOther text that is long enough to be kept.\n\n"
        "## Other\n\n| Key | Value |\n|---|---|\n| y | 2 |\n"
    ))
    rows = {json.dumps(c["content"]): c["metadata"]["parent_chunk_id"] for c in chunks if c["chunk_type"] == "table_row"}
    page = _id(chunks, "# Page")
    # The first table follows a list (dropped headings handed on by the list
    # chunker), the second follows prose (handed on by the prose chunker).
    assert sorted(rows.values()) == [page, page]
    assert _parents(chunks)["a list item in the first example"] == _id(chunks, "## Example")
