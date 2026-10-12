"""Tests for the get_section MCP tool (prose navigation)."""

import json
from unittest.mock import patch

import pytest

from opencrane.config import OpenCraneConfig
from opencrane.mcp import server as s
from opencrane.mcp.auth import runtime
from opencrane.mcp.http_server import build_app
from opencrane.rag.chunker import _annotate_prose_navigation
from opencrane.shared.models.chunk import Chunk


class FakeMilvus:
    """In-memory stand-in exposing the lookups get_section uses."""

    def __init__(self, rows):
        self.rows = {r["chunk_id"]: r for r in rows}

    def get_chunk(self, chunk_id):
        return self.rows.get(chunk_id)

    def query_by_values(self, field, values, chunk_type=None, limit=16384):
        return [r for r in self.rows.values()
                if r.get(field) in values and (chunk_type is None or r["chunk_type"] == chunk_type)]

    def query_by_prefix(self, field, prefix, chunk_type=None, limit=16384):
        return [r for r in self.rows.values()
                if (r.get(field) or "").startswith(prefix)
                and (chunk_type is None or r["chunk_type"] == chunk_type)]

    def distinct_chunk_types(self):
        return {r["chunk_type"] for r in self.rows.values()}

    def has_prose_navigation(self):
        return True


def _rows(pages):
    """Chunk and annotate ``{(source_name, url): [(chunk_id, content), ...]}`` into Milvus rows."""
    chunks, names = [], {}
    for (name, url), items in pages.items():
        for chunk_id, content, *preceding in items:
            if content is None:  # a non-prose chunk between prose chunks
                chunks.append(Chunk(chunk_id=chunk_id, content="echo", source_file="f",
                                    chunk_type="code_snippet", metadata={"language": "bash"},
                                    token_count=1))
            else:
                meta = {"source_url": url} if url else {}
                if content.startswith("## 5 "):
                    meta["section_anchor"] = "5-functional-description"
                chunk = Chunk(chunk_id=chunk_id, content=content, source_file="spec.md",
                              chunk_type="prose", metadata=meta, token_count=1)
                # Headings of dropped heading-only sections right before this chunk.
                chunk._preceding_headings = preceding[0] if preceding else []
                chunks.append(chunk)
            names[chunk_id] = name
    _annotate_prose_navigation(chunks, OpenCraneConfig())
    return [{
        "chunk_id": c.chunk_id, "content": c.content, "chunk_type": c.chunk_type,
        "source_file": c.source_file, "source_name": names[c.chunk_id],
        "metadata_json": json.dumps(c.metadata),
        "clause_id": c.metadata.get("clause_id") or "",
        "parent_chunk_id": c.metadata.get("parent_chunk_id") or "",
    } for c in chunks]


SPEC = {
    ("specs", "https://d/23501.md"): [
        ("h1", "# TS 23.501 System architecture\n\nIntro."),
        ("c5", "## 5 Functional description\n\nGeneral text."),
        ("c51", "### 5.1 General\n\nText of 5.1."),
        ("c52", "### 5.2 Access\n\nBefore code."),
        ("code", None),
        ("c52b", "After code.\n\n#### 5.2.1 Inner\n\nInner one.\n\n```\n#### 5.2.9 fenced\n```\n\n#### 5.2.2 Second\n\nInner two."),
        ("c53", "### 5.3 Last\n\nText of 5.3."),
        ("annex", "## Annex C (informative): Extras\n\nAnnex text."),
        ("c4", "### C.4 Sub annex\n\nSub annex text."),
    ],
}


@pytest.fixture
def milvus(monkeypatch):
    fake = FakeMilvus(_rows(SPEC))
    monkeypatch.setattr(s, "get_milvus_service", lambda: fake)
    return fake


async def _call(args):
    result = await s.get_section(args)
    return result[0].text


@pytest.mark.anyio
async def test_by_clause_lists_direct_subsections(milvus):
    text = await _call({"clause_id": "5"})
    assert text.startswith("Section: TS 23.501 System architecture > 5 Functional description\n")
    assert "Clause: 5\n" in text
    assert "Source: https://d/23501.md#5-functional-description\n" in text
    assert "Source Name: specs\n" in text
    assert "Parent Chunk ID: h1\n" in text
    assert "General text." in text
    assert "Sub-sections (3):" in text
    assert "  - 5.2 Access (chunk_id=c52)" in text
    # Only the listing, not the sub-section bodies, without include_subsections.
    assert "Text of 5.1." not in text


@pytest.mark.anyio
async def test_continuation_chunk_resolves_to_whole_section(milvus):
    text = await _call({"chunk_id": "c52b"})
    assert "Chunk ID: c52 (continued in c52b)" in text
    assert "Before code.\n\nAfter code." in text
    assert "Clause: 5.2\n" in text


@pytest.mark.anyio
async def test_include_subsections_returns_nested_text_in_order(milvus):
    text = await _call({"chunk_id": "h1", "include_subsections": True})
    assert "Sub-sections (7 chunks):" in text
    assert text.index("Text of 5.1.") < text.index("Before code.") < text.index("Sub annex text.")


@pytest.mark.anyio
async def test_include_subsections_caps_output(milvus, monkeypatch):
    monkeypatch.setattr(s, "_SECTION_MAX_SUBSECTION_CHUNKS", 2)
    text = await _call({"chunk_id": "h1", "include_subsections": True})
    assert "... 5 more sub-section chunks not shown" in text


@pytest.mark.anyio
async def test_neighbors_return_whole_sections_in_document_order(milvus):
    text = await _call({"clause_id": "5.2", "neighbors": 2})
    prev_51 = text.index("=== Previous section ===\nSection: TS 23.501 System architecture > 5 Functional description > 5.1 General")
    prev_5 = text.index("=== Previous section ===\nSection: TS 23.501 System architecture > 5 Functional description\n")
    nxt = text.index("=== Next section ===\nSection: TS 23.501 System architecture > 5 Functional description > 5.3 Last")
    assert prev_5 < prev_51 < nxt
    assert "Annex text." in text  # second next section


@pytest.mark.anyio
async def test_neighbors_stop_at_page_edges_and_are_clamped(milvus):
    text = await _call({"chunk_id": "c4", "neighbors": 99})
    assert "=== Next section ===" not in text
    assert text.count("=== Previous section ===") == s._SECTION_MAX_NEIGHBORS
    text = await _call({"chunk_id": "h1", "neighbors": "lots"})
    assert "=== " not in text


@pytest.mark.anyio
async def test_inner_clause_is_sliced_from_enclosing_section(milvus):
    text = await _call({"clause_id": "5.2.1"})
    assert "Clause: 5.2.1\n" in text
    assert "#### 5.2.1 Inner\n\nInner one." in text
    assert "Inner two." not in text and "Before code." not in text
    assert "Sub-sections" not in text
    # Runs to the end of the section when it is the last inner heading.
    text = await _call({"clause_id": "5.2.2"})
    assert text.rstrip().endswith("Inner two.")


@pytest.mark.anyio
async def test_inner_clause_not_found_names_enclosing_clause(milvus):
    text = await _call({"clause_id": "5.2.9"})  # only inside a code fence
    assert text == "No section found for clause_id='5.2.9' (nearest enclosing clause: '5.2', chunk_id=c52)."


@pytest.mark.anyio
async def test_annex_clause_falls_back_to_annex_heading(milvus):
    text = await _call({"clause_id": "C.7"})
    assert text.startswith("No section found for clause_id='C.7' (nearest enclosing clause: 'Annex C'")
    text = await _call({"clause_id": "C.4", "source": "23.501"})
    assert "Sub annex text." in text


@pytest.mark.anyio
async def test_lookup_errors(milvus):
    assert await _call({}) == "Error: provide chunk_id or clause_id."
    assert await _call(None) == "Error: provide chunk_id or clause_id."
    assert await _call({"chunk_id": "missing"}) == "No prose section found for chunk_id='missing'."
    assert await _call({"chunk_id": "code"}) == "No prose section found for chunk_id='code'."
    assert await _call({"clause_id": "9"}) == "No section found for clause_id='9'."
    assert await _call({"clause_id": "5", "source": "other"}) == "No section found for clause_id='5' in source 'other'."


@pytest.mark.anyio
async def test_clause_in_several_documents_asks_for_source(monkeypatch):
    pages = dict(SPEC)
    pages[("other", "https://d/23502.md")] = [
        ("o1", "# TS 23.502 Procedures\n\nIntro."),
        ("o5", "## 5 Procedures\n\nOther text."),
    ]
    fake = FakeMilvus(_rows(pages))
    monkeypatch.setattr(s, "get_milvus_service", lambda: fake)
    text = await _call({"clause_id": "5"})
    assert text.startswith("Clause '5' appears in 2 documents; pass source to pick one:")
    assert "TS 23.502 Procedures | source=other | url=https://d/23502.md | chunk_id=o5" in text
    text = await _call({"clause_id": "5", "source": "procedures"})
    assert "Other text." in text and "General text." not in text


@pytest.mark.anyio
async def test_headingless_page_and_disambiguation_fallbacks(monkeypatch):
    rows = _rows({
        ("", None): [("p0", "Preamble with no heading."), ("p1", "## 7 Seven\n\nText.")],
        ("x", ""): [("q1", "## 7 Again\n\nMore.")],
    })
    # q1 page has an empty URL, so it is grouped apart from the first page.
    for row in rows:
        if row["chunk_id"] == "q1":
            row["metadata_json"] = json.dumps({**json.loads(row["metadata_json"]), "heading_path": ""})
    fake = FakeMilvus(rows)
    monkeypatch.setattr(s, "get_milvus_service", lambda: fake)
    text = await _call({"chunk_id": "p0", "neighbors": 1})
    assert text.startswith("Section: (before the first heading)\n")
    assert "Source: spec.md\n" in text and "Source Name" not in text
    assert "=== Next section ===" in text
    text = await _call({"clause_id": "7"})
    assert "  - 7 Seven | source=- | url=- | chunk_id=p1" in text
    assert "  - x | source=x | url=- | chunk_id=q1" in text


@pytest.mark.anyio
async def test_clause_lookup_prefers_heading_chunk(monkeypatch):
    rows = _rows({("s", "u"): [("a", "## 4 Four\n\nText."), ("b", "More of four.")]})
    fake = FakeMilvus(rows)
    monkeypatch.setattr(s, "get_milvus_service", lambda: fake)
    # Only the continuation chunk matches the clause: still resolves to the section head.
    fake.rows["a"]["clause_id"] = ""
    text = await _call({"clause_id": "4"})
    assert "Chunk ID: a (continued in b)" in text


@pytest.mark.anyio
async def test_tolerates_bad_metadata_and_heading_scan_edges(monkeypatch):
    fake = FakeMilvus([
        {"chunk_id": "x", "chunk_type": "prose", "content": "", "metadata_json": "{bad"},
        {"chunk_id": "y", "chunk_type": "prose", "content": "## T\n\nBody", "metadata_json": "[1]"},
    ])
    monkeypatch.setattr(s, "get_milvus_service", lambda: fake)
    text = await _call({"chunk_id": "x"})
    assert text.startswith("Section: (before the first heading)")
    text = await _call({"chunk_id": "y"})
    assert "Body" in text


@pytest.mark.anyio
async def test_authorization_filters_sources(milvus, monkeypatch):
    monkeypatch.setattr(runtime, "current_allowed_sources", lambda: ("other",))
    assert await _call({"chunk_id": "c5"}) == "No prose section found for chunk_id='c5'."
    assert await _call({"clause_id": "5"}) == "No section found for clause_id='5'."

    monkeypatch.setattr(runtime, "current_allowed_sources", lambda: ())
    assert await _call({"chunk_id": "c5"}) == "No section found."

    class Policy:
        def authorize(self, scopes, requested):
            return ["specs"]

    monkeypatch.setattr(runtime, "current_allowed_sources", lambda: None)
    monkeypatch.setattr(runtime, "get_access_policy", lambda: Policy())
    assert "General text." in await _call({"chunk_id": "c5"})


@pytest.mark.anyio
async def test_failure_is_reported(monkeypatch):
    class Broken:
        def get_chunk(self, chunk_id):
            raise RuntimeError("db down")

    monkeypatch.setattr(s, "get_milvus_service", lambda: Broken())
    assert await _call({"chunk_id": "a"}) == "Failed to fetch section: db down"


@pytest.mark.anyio
async def test_call_tool_dispatches_get_section(milvus):
    result = await s.call_tool("get_section", {"clause_id": "5.1"})
    assert "Text of 5.1." in result[0].text


# --- advertisement -------------------------------------------------------------

def test_has_prose_navigation(monkeypatch, milvus):
    monkeypatch.setattr(s, "_get_indexed_chunk_types", lambda: {"code_snippet"})
    assert s._has_prose_navigation() is False
    monkeypatch.setattr(s, "_get_indexed_chunk_types", lambda: {"prose"})
    assert s._has_prose_navigation() is True
    monkeypatch.setattr(milvus, "has_prose_navigation", lambda: False)
    assert s._has_prose_navigation() is False


@pytest.mark.parametrize("has_nav", [True, False])
@pytest.mark.anyio
async def test_tool_advertised_only_with_navigation_metadata(has_nav):
    with patch.object(s, "_get_indexed_chunk_types", return_value={"prose"}), \
            patch.object(s, "_has_prose_navigation", return_value=has_nav), \
            patch.object(s, "_get_source_keys", return_value=[]), \
            patch.object(s, "_get_source_topics", return_value=[]):
        stdio = {t.name: t for t in await s.list_tools()}
        http = {t.name: t for t in await build_app().list_tools()}
    assert set(stdio) == set(http)
    assert ("get_section" in stdio) is has_nav
    assert ("get_metadata_schema" in stdio) is has_nav
    if has_nav:
        assert stdio["get_section"].inputSchema == s.GET_SECTION_TOOL_SCHEMA
        assert http["get_section"].inputSchema == s.GET_SECTION_TOOL_SCHEMA
        assert http["get_section"].description == s.GET_SECTION_TOOL_DESCRIPTION


@pytest.mark.anyio
async def test_metadata_schema_for_prose_documents_navigation_fields():
    text = (await s.get_metadata_schema({"chunk_type": "prose"}))[0].text
    assert "## Universal Metadata" in text
    assert "## Prose Navigation Metadata" in text
    assert "`clause_id`" in text and "`next_chunk_id`" in text
    assert "## List Item Metadata" not in text


HEADING_ONLY = {
    ("specs", "https://d/23501.md"): [
        ("h1", "# TS 23.501\n\nIntro."),
        ("c61", "### 6.1 First\n\nText 6.1.", ["## 6 Empty clause"]),
        ("c611", "#### 6.1.1 Deeper\n\nText 6.1.1."),
        ("c62", "### 6.2 Second\n\nText 6.2."),
        ("d1", "### D.1 Annex sub\n\nText D.1.", ["## Annex D (normative): Empty"]),
    ],
}


@pytest.mark.anyio
async def test_heading_only_clause_lists_its_subsections(monkeypatch):
    fake = FakeMilvus(_rows(HEADING_ONLY))
    monkeypatch.setattr(s, "get_milvus_service", lambda: fake)
    assert json.loads(fake.rows["c61"]["metadata_json"])["heading_path"] == "TS 23.501 > 6 Empty clause > 6.1 First"
    text = await _call({"clause_id": "6"})
    assert text.startswith("Section: TS 23.501 > 6 Empty clause\nClause: 6\nSource: https://d/23501.md\n")
    assert "This section has no text of its own" in text
    assert "Sub-sections (2):\n  - 6.1 First (chunk_id=c61)\n  - 6.2 Second (chunk_id=c62)\n" in text
    text = await _call({"clause_id": "Annex D"})
    assert "  - D.1 Annex sub (chunk_id=d1)" in text


@pytest.mark.anyio
async def test_heading_only_clause_in_several_documents(monkeypatch):
    pages = dict(HEADING_ONLY)
    pages[("other", "https://d/23502.md")] = [("o61", "### 6.1 Other\n\nX.", ["## 6 Empty"])]
    fake = FakeMilvus(_rows(pages))
    monkeypatch.setattr(s, "get_milvus_service", lambda: fake)
    text = await _call({"clause_id": "6"})
    assert text.startswith("Clause '6' appears in 2 documents")


@pytest.mark.anyio
async def test_heading_only_clause_with_only_continuation_rows(monkeypatch):
    rows = _rows({("s", "u"): [("a", "Text under a dropped heading.", ["## 7 Empty", "### 7.1 Also empty"])]})
    fake = FakeMilvus(rows)
    monkeypatch.setattr(s, "get_milvus_service", lambda: fake)
    text = await _call({"clause_id": "7"})
    assert text.startswith("Section: 7 Empty\nClause: 7\n")
    assert "Sub-sections (0):" in text
