"""Tests for list_item MCP features: grouping, get_list_members, metadata schema filter."""

import json
from unittest.mock import AsyncMock, Mock, patch

import pytest

from opencrane.mcp.server import (
    _get_list_members,
    _group_list_item_results,
    _has_list_item_chunks,
    get_list_members,
    get_metadata_schema,
    list_tools,
)


def _write_chunks(tmp_path, chunks):
    (tmp_path / ".opencrane").mkdir(exist_ok=True)
    (tmp_path / ".opencrane" / "chunks.json").write_text(json.dumps(chunks), encoding="utf-8")


def _reset_caches():
    import opencrane.mcp.server as server_module
    server_module._chunk_index = None
    server_module._chunk_source_map = None


def test_has_list_item_chunks_true(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _reset_caches()
    _write_chunks(tmp_path, [
        {"chunk_id": "c1", "content": "hello", "chunk_type": "prose"},
        {"chunk_id": "c2", "content": "# H\nitem", "chunk_type": "list_item",
         "metadata": {"list_id": "abc", "list_style": "unordered", "position": 1}},
    ])
    assert _has_list_item_chunks() is True


def test_has_list_item_chunks_false(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _reset_caches()
    _write_chunks(tmp_path, [
        {"chunk_id": "c1", "content": "hello", "chunk_type": "prose"},
    ])
    assert _has_list_item_chunks() is False


def test_get_list_members_returns_items_in_order(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _reset_caches()
    _write_chunks(tmp_path, [
        {"chunk_id": "i2", "content": "# H\nSecond", "chunk_type": "list_item",
         "metadata": {"list_id": "lx", "position": 2}},
        {"chunk_id": "i1", "content": "# H\nFirst", "chunk_type": "list_item",
         "metadata": {"list_id": "lx", "position": 1}},
        {"chunk_id": "other", "content": "# H\nOther", "chunk_type": "list_item",
         "metadata": {"list_id": "ly", "position": 1}},
        {"chunk_id": "p", "content": "prose", "chunk_type": "prose"},
    ])
    members = _get_list_members("lx")
    assert [m["chunk_id"] for m in members] == ["i1", "i2"]
    # Other lists are excluded
    assert _get_list_members("ly") == [m for m in _get_list_members("ly")]
    assert len(_get_list_members("ly")) == 1


@pytest.mark.anyio
async def test_get_list_members_tool_formats_output(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _reset_caches()
    _write_chunks(tmp_path, [
        {"chunk_id": "i1", "content": "# Section\nFirst", "chunk_type": "list_item",
         "metadata": {"list_id": "lx", "list_style": "unordered",
                      "position": 1, "depth": 0, "total_siblings": 2,
                      "breadcrumb_path": "Section"}},
        {"chunk_id": "i2", "content": "# Section\nSecond", "chunk_type": "list_item",
         "metadata": {"list_id": "lx", "list_style": "unordered",
                      "position": 2, "depth": 0, "total_siblings": 2,
                      "breadcrumb_path": "Section"}},
    ])
    result = await get_list_members({"list_id": "lx"})
    text = result[0].text
    assert "List (2 of 2 items" in text
    assert "Location: Section" in text
    assert "[1] First" in text
    assert "[2] Second" in text


@pytest.mark.anyio
async def test_get_list_members_missing_id_error():
    result = await get_list_members({})
    assert "list_id must be" in result[0].text


@pytest.mark.anyio
async def test_get_list_members_unknown_id(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _reset_caches()
    _write_chunks(tmp_path, [])
    result = await get_list_members({"list_id": "nope"})
    assert "No list found" in result[0].text


def test_group_list_item_results_collapses_shared_list_id():
    """Two hits on the same list_id → one grouped slot with max score."""
    results = [
        {"chunk_id": "p", "chunk_type": "prose", "content": "P", "distance": 0.9,
         "metadata_json": "{}"},
        {"chunk_id": "i1", "chunk_type": "list_item", "content": "# H\nA", "distance": 0.8,
         "metadata_json": json.dumps({"list_id": "lx", "position": 1, "total_siblings": 3,
                                      "sibling_ids": ["i2", "i3"],
                                      "sibling_previews": ["B", "C"]})},
        {"chunk_id": "i2", "chunk_type": "list_item", "content": "# H\nB", "distance": 0.85,
         "metadata_json": json.dumps({"list_id": "lx", "position": 2, "total_siblings": 3,
                                      "sibling_ids": ["i1", "i3"],
                                      "sibling_previews": ["A", "C"]})},
    ]
    grouped = _group_list_item_results(results)
    # Expect prose + one grouped list slot = 2 total
    assert len(grouped) == 2
    # Prose pass-through, untouched
    assert grouped[0]["chunk_id"] == "p"
    assert "_grouped" not in grouped[0]
    # Grouped slot
    g = grouped[1]
    assert g["_grouped"] is True
    assert g["distance"] == 0.85  # max of 0.8, 0.85
    items = g["_grouped_items"]
    assert [x["chunk_id"] for x in items] == ["i1", "i2"]  # sorted by position


def test_group_list_item_results_single_item_is_pass_through():
    """A lone list_item hit must NOT be collapsed (no duplicate-slot problem)."""
    results = [
        {"chunk_id": "i1", "chunk_type": "list_item", "content": "# H\nA", "distance": 0.8,
         "metadata_json": json.dumps({"list_id": "lx", "position": 1})},
    ]
    grouped = _group_list_item_results(results)
    assert len(grouped) == 1
    assert "_grouped" not in grouped[0]


@patch('opencrane.mcp.server.get_embeddings_service')
@patch('opencrane.mcp.server.get_milvus_service')
@pytest.mark.anyio
async def test_search_docs_groups_list_items(mock_milvus_get, mock_embeddings_get,
                                             tmp_path, monkeypatch):
    """End-to-end: two list_item hits with same list_id render as one grouped result."""
    from opencrane.mcp.server import _search_documentation_impl

    monkeypatch.chdir(tmp_path)
    _reset_caches()
    _write_chunks(tmp_path, [])

    mock_embeddings = Mock()
    mock_model = Mock()
    mock_model.encode.return_value = [[0.1] * 768]
    mock_embeddings.model = mock_model
    mock_embeddings_get.return_value = mock_embeddings

    mock_milvus = Mock()
    mock_milvus.search.return_value = [
        {"chunk_id": "i1", "content": "# Migration guide\n1. Install base.",
         "source_file": "docs.md", "chunk_type": "list_item",
         "metadata_json": json.dumps({"list_id": "LID", "position": 1,
                                      "total_siblings": 2, "list_style": "ordered",
                                      "breadcrumb_path": "Migration guide",
                                      "sibling_ids": ["i2"],
                                      "sibling_previews": ["2. Install support."]}),
         "distance": 0.7},
        {"chunk_id": "i2", "content": "# Migration guide\n2. Install support.",
         "source_file": "docs.md", "chunk_type": "list_item",
         "metadata_json": json.dumps({"list_id": "LID", "position": 2,
                                      "total_siblings": 2, "list_style": "ordered",
                                      "breadcrumb_path": "Migration guide",
                                      "sibling_ids": ["i1"],
                                      "sibling_previews": ["1. Install base."]}),
         "distance": 0.75},
    ]
    mock_milvus_get.return_value = mock_milvus

    results = await _search_documentation_impl({
        "query": "migration steps", "limit": 5, "search_mode": "semantic",
    })
    # Should collapse to a single result slot
    assert len(results) == 1
    text = results[0].text
    assert "Matched List (2 of 2 items)" in text
    assert "Location: Migration guide" in text
    assert "[1] 1. Install base." in text
    assert "[2] 2. Install support." in text
    assert "List ID: LID" in text
    assert "get_list_members(list_id='LID')" in text


@pytest.mark.anyio
async def test_get_metadata_schema_filter_list_item():
    result = await get_metadata_schema({"chunk_type": "list_item"})
    text = result[0].text
    # Should contain the list_item section
    assert "List Item Metadata" in text
    assert "sibling_previews" in text
    # Universal metadata is also included
    assert "Universal Metadata" in text
    # Should NOT include CRD-specific fields
    assert "crd_kind" not in text
    assert "openapi_version" not in text


@pytest.mark.anyio
async def test_get_metadata_schema_unknown_chunk_type():
    result = await get_metadata_schema({"chunk_type": "bogus"})
    assert "Unknown chunk_type" in result[0].text


@pytest.mark.anyio
async def test_get_metadata_schema_no_args_returns_full():
    result = await get_metadata_schema({})
    text = result[0].text
    assert "Chunk Metadata Schema" in text
    # Full doc contains both list_item and crd
    assert "List Item Metadata" in text
    assert "CRD-Specific Metadata" in text


@patch('opencrane.mcp.server._has_list_item_chunks', return_value=True)
@patch('opencrane.mcp.server._has_yaml_chunks', return_value=False)
@patch('opencrane.mcp.server._get_indexed_chunk_types', return_value={"prose", "list_item"})
@patch('opencrane.mcp.server._get_source_topics', return_value=[])
@pytest.mark.anyio
async def test_list_tools_registers_list_tools(topics, types, has_yaml, has_list):
    """When list_item chunks are indexed, get_list_members and get_metadata_schema are exposed."""
    tools = await list_tools()
    names = [t.name for t in tools]
    assert "get_list_members" in names
    assert "get_metadata_schema" in names
    # Ensure list_item appears in the chunk_types filter
    enum = tools[0].inputSchema["properties"]["chunk_types"]["items"]["enum"]
    assert "list_item" in enum


@pytest.mark.anyio
async def test_call_tool_get_list_members_wired():
    """Verify get_list_members routes through call_tool dispatch."""
    from opencrane.mcp.server import call_tool
    with patch('opencrane.mcp.server.get_list_members') as mock_handler:
        mock_handler.return_value = [Mock(text="ok")]
        await call_tool("get_list_members", {"list_id": "abc"})
        mock_handler.assert_called_once_with({"list_id": "abc"})


def test_extract_schema_section_missing_heading_returns_none():
    from opencrane.mcp.server import _extract_schema_section
    assert _extract_schema_section("some\ntext", "Nonexistent Heading") is None


def test_extract_schema_section_trailing_section():
    from opencrane.mcp.server import _extract_schema_section
    # When the requested heading is the LAST top-level section, the slice runs
    # to end-of-file instead of up to the next '\n## '.
    doc = (
        "# Top\n\nIntro\n\n"
        "## Alpha\n\nalpha body\n\n"
        "## Omega\n\nomega body — last section"
    )
    result = _extract_schema_section(doc, "Omega")
    assert result is not None
    assert result.startswith("\n## Omega")
    assert "omega body" in result


@patch('opencrane.mcp.server.get_embeddings_service')
@patch('opencrane.mcp.server.get_milvus_service')
@pytest.mark.anyio
async def test_grouped_list_item_renders_unmatched_previews(mock_milvus_get, mock_embeddings_get,
                                                            tmp_path, monkeypatch):
    """Grouped list_item slot lists unmatched siblings under their own header."""
    from opencrane.mcp.server import _search_documentation_impl

    monkeypatch.chdir(tmp_path)
    _reset_caches()
    _write_chunks(tmp_path, [])

    mock_embeddings = Mock()
    mock_model = Mock()
    mock_model.encode.return_value = [[0.1] * 768]
    mock_embeddings.model = mock_model
    mock_embeddings_get.return_value = mock_embeddings

    mock_milvus = Mock()
    # Two hits (i1, i2) on a 3-item list; i3 is unmatched.
    mock_milvus.search.return_value = [
        {"chunk_id": "i1", "content": "# Section\n- A", "source_file": "d.md",
         "chunk_type": "list_item", "distance": 0.8,
         "metadata_json": json.dumps({"list_id": "LID", "position": 1,
                                      "total_siblings": 3, "list_style": "unordered",
                                      "breadcrumb_path": "Section",
                                      "sibling_ids": ["i2", "i3"],
                                      "sibling_previews": ["B", "C"]})},
        {"chunk_id": "i2", "content": "# Section\n- B", "source_file": "d.md",
         "chunk_type": "list_item", "distance": 0.85,
         "metadata_json": json.dumps({"list_id": "LID", "position": 2,
                                      "total_siblings": 3, "list_style": "unordered",
                                      "breadcrumb_path": "Section",
                                      "sibling_ids": ["i1", "i3"],
                                      "sibling_previews": ["A", "C"]})},
    ]
    mock_milvus_get.return_value = mock_milvus

    results = await _search_documentation_impl({
        "query": "things", "limit": 5, "search_mode": "semantic",
    })
    text = results[0].text
    assert "Matched List (2 of 3 items)" in text
    assert "Other items in list (not matched):" in text
    assert "  - C" in text


def test_get_source_topics_reads_mapping_file(tmp_path, monkeypatch):
    """Exercise the real _get_source_topics code path (not mocked)."""
    from opencrane.mcp.server import _get_source_topics
    mapping = tmp_path / "config.yaml"
    mapping.write_text("sources:\n  Acme/example-repo: docs\n  Other/project-docs: .\n")
    monkeypatch.setenv("MAPPING_FILE", str(mapping))
    topics = _get_source_topics()
    # Prettified (hyphens → spaces), last path component
    assert "example repo" in topics
    assert "project docs" in topics


def test_get_source_topics_malformed_yaml_returns_empty(tmp_path, monkeypatch):
    from opencrane.mcp.server import _get_source_topics
    mapping = tmp_path / "broken.yaml"
    mapping.write_text("sources: [unclosed_list\n")
    monkeypatch.setenv("MAPPING_FILE", str(mapping))
    assert _get_source_topics() == []


def test_get_source_topics_missing_file_returns_empty(tmp_path, monkeypatch):
    from opencrane.mcp.server import _get_source_topics
    monkeypatch.setenv("MAPPING_FILE", str(tmp_path / "does-not-exist.yaml"))
    assert _get_source_topics() == []


def test_get_source_keys_returns_path_keys(tmp_path, monkeypatch):
    from opencrane.mcp.server import _get_source_keys
    mapping = tmp_path / "config.yaml"
    mapping.write_text("sources:\n  Acme/example-repo: docs\n  Other/project-docs: .\n")
    monkeypatch.setenv("MAPPING_FILE", str(mapping))
    assert _get_source_keys() == ["Acme/example-repo", "Other/project-docs"]


def test_get_source_keys_missing_file_returns_empty(tmp_path, monkeypatch):
    from opencrane.mcp.server import _get_source_keys
    monkeypatch.setenv("MAPPING_FILE", str(tmp_path / "missing.yaml"))
    assert _get_source_keys() == []


def test_get_source_keys_malformed_yaml_returns_empty(tmp_path, monkeypatch):
    from opencrane.mcp.server import _get_source_keys
    mapping = tmp_path / "broken.yaml"
    mapping.write_text("sources: [unclosed\n")
    monkeypatch.setenv("MAPPING_FILE", str(mapping))
    assert _get_source_keys() == []
