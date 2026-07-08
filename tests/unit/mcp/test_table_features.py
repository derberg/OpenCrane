"""Tests for table MCP features: get_table_members, search tip, metadata schema filter, grouping."""

import json
from unittest.mock import Mock, patch

import pytest

from opencrane.mcp import server
from opencrane.mcp.server import _group_table_row_results, _format_grouped_table_row


def test_get_table_members_returns_rows_by_index(monkeypatch):
    index = {
        "r2": {"chunk_id": "r2", "chunk_type": "table_row", "content": "A: b.",
               "metadata": {"table_id": "t1", "row_index": 2}},
        "r1": {"chunk_id": "r1", "chunk_type": "table_row", "content": "A: a.",
               "metadata": {"table_id": "t1", "row_index": 1}},
        "x": {"chunk_id": "x", "chunk_type": "prose", "content": "nope", "metadata": {}},
    }
    monkeypatch.setattr(server, "_build_chunk_index", lambda: index)
    members = server._get_table_members("t1")
    assert [m["chunk_id"] for m in members] == ["r1", "r2"]


def test_has_table_row_chunks(monkeypatch):
    monkeypatch.setattr(server, "_get_indexed_chunk_types", lambda: {"table_row", "prose"})
    assert server._has_table_row_chunks() is True
    monkeypatch.setattr(server, "_get_indexed_chunk_types", lambda: {"prose"})
    assert server._has_table_row_chunks() is False


@pytest.mark.anyio
async def test_get_table_members_tool_formats_output(monkeypatch):
    """get_table_members tool returns rows formatted as text."""
    index = {
        "r1": {"chunk_id": "r1", "chunk_type": "table_row", "content": "A: x. B: y.",
               "metadata": {"table_id": "t1", "row_index": 1}},
    }
    monkeypatch.setattr(server, "_build_chunk_index", lambda: index)
    result = await server.get_table_members({"table_id": "t1"})
    text = result[0].text
    assert "A: x. B: y." in text


@pytest.mark.anyio
async def test_get_table_members_missing_id_error():
    result = await server.get_table_members({})
    assert "table_id must be" in result[0].text


@pytest.mark.anyio
async def test_get_table_members_unknown_id(monkeypatch):
    monkeypatch.setattr(server, "_build_chunk_index", lambda: {})
    result = await server.get_table_members({"table_id": "nope"})
    assert "No table found" in result[0].text


@patch('opencrane.mcp.server._has_table_row_chunks', return_value=True)
@patch('opencrane.mcp.server._has_list_item_chunks', return_value=False)
@patch('opencrane.mcp.server._has_yaml_chunks', return_value=False)
@patch('opencrane.mcp.server._get_indexed_chunk_types', return_value={"prose", "table_row"})
@patch('opencrane.mcp.server._get_source_topics', return_value=[])
@pytest.mark.anyio
async def test_list_tools_registers_table_tools(topics, types, has_yaml, has_list, has_table):
    """When table_row chunks are indexed, get_table_members and get_metadata_schema are exposed."""
    tools = await server.list_tools()
    names = [t.name for t in tools]
    assert "get_table_members" in names
    assert "get_metadata_schema" in names


@pytest.mark.anyio
async def test_call_tool_get_table_members_wired():
    """Verify get_table_members routes through call_tool dispatch."""
    with patch.object(server, 'get_table_members') as mock_handler:
        mock_handler.return_value = [Mock(text="ok")]
        await server.call_tool("get_table_members", {"table_id": "t1"})
        mock_handler.assert_called_once_with({"table_id": "t1"})


@patch('opencrane.mcp.server.get_embeddings_service')
@patch('opencrane.mcp.server.get_milvus_service')
@pytest.mark.anyio
async def test_search_docs_table_row_tip(mock_milvus_get, mock_embeddings_get, monkeypatch):
    """A table_row search result gets a get_table_members tip appended."""
    import opencrane.mcp.server as server_module

    # Reset caches
    server_module._chunk_index = None

    # No chunks.json needed since we monkeypatch the index and source map
    monkeypatch.setattr(server_module, "_build_chunk_index", lambda: {})

    mock_embeddings = Mock()
    mock_model = Mock()
    mock_model.encode.return_value = [[0.1] * 768]
    mock_embeddings.model = mock_model
    mock_embeddings_get.return_value = mock_embeddings

    mock_milvus = Mock()
    mock_milvus.search.return_value = [
        {
            "chunk_id": "row1",
            "content": "Col: value.",
            "source_file": "docs.md",
            "chunk_type": "table_row",
            "metadata_json": json.dumps({
                "table_id": "tbl-abc",
                "row_index": 1,
            }),
            "distance": 0.9,
        },
    ]
    mock_milvus_get.return_value = mock_milvus

    results = await server_module._search_documentation_impl({
        "query": "table data", "limit": 5, "search_mode": "semantic",
    })
    assert len(results) == 1
    text = results[0].text
    assert "get_table_members(table_id='tbl-abc')" in text


# ---------------------------------------------------------------------------
# _group_table_row_results tests
# ---------------------------------------------------------------------------

def test_group_table_row_results_collapses_shared_table_id():
    """Two hits on the same table_id collapse into one grouped slot with max score."""
    results = [
        {"chunk_id": "p", "chunk_type": "prose", "content": "P", "distance": 0.9,
         "metadata_json": "{}"},
        {"chunk_id": "r1", "chunk_type": "table_row", "content": "Row A", "distance": 0.8,
         "metadata_json": json.dumps({"table_id": "tx", "row_index": 1, "total_rows": 3,
                                      "sibling_ids": ["r2", "r3"],
                                      "sibling_previews": ["Row B", "Row C"]})},
        {"chunk_id": "r2", "chunk_type": "table_row", "content": "Row B", "distance": 0.85,
         "metadata_json": json.dumps({"table_id": "tx", "row_index": 2, "total_rows": 3,
                                      "sibling_ids": ["r1", "r3"],
                                      "sibling_previews": ["Row A", "Row C"]})},
    ]
    grouped = _group_table_row_results(results)
    # Prose + one grouped table slot = 2 total
    assert len(grouped) == 2
    # Prose passes through untouched
    assert grouped[0]["chunk_id"] == "p"
    assert "_grouped_table" not in grouped[0]
    # Grouped slot
    g = grouped[1]
    assert g["_grouped_table"] is True
    assert g["distance"] == 0.85  # max of 0.8, 0.85
    items = g["_grouped_items"]
    assert [x["chunk_id"] for x in items] == ["r1", "r2"]  # sorted by row_index


def test_group_table_row_results_single_row_is_pass_through():
    """A lone table_row hit must NOT be collapsed."""
    results = [
        {"chunk_id": "r1", "chunk_type": "table_row", "content": "Row A", "distance": 0.8,
         "metadata_json": json.dumps({"table_id": "tx", "row_index": 1})},
    ]
    grouped = _group_table_row_results(results)
    assert len(grouped) == 1
    assert "_grouped_table" not in grouped[0]


def test_group_table_row_results_non_table_row_passes_through():
    """Non-table_row results (including already-grouped list slots) pass through unchanged."""
    results = [
        {"chunk_id": "p", "chunk_type": "prose", "content": "P", "distance": 0.9,
         "metadata_json": "{}"},
        {"chunk_id": "li", "chunk_type": "list_item", "content": "item", "distance": 0.7,
         "_grouped": True, "_grouped_items": [],
         "metadata_json": json.dumps({"list_id": "L1", "position": 1})},
    ]
    grouped = _group_table_row_results(results)
    assert len(grouped) == 2
    assert grouped[0]["chunk_id"] == "p"
    assert grouped[1]["chunk_id"] == "li"
    assert "_grouped_table" not in grouped[0]
    assert "_grouped_table" not in grouped[1]


# ---------------------------------------------------------------------------
# _format_grouped_table_row tests
# ---------------------------------------------------------------------------

def _make_grouped_table_result(members_meta, member_contents, distances):
    """Build a grouped table result dict matching the shape produced by _group_table_row_results."""
    members = []
    for meta, content, dist in zip(members_meta, member_contents, distances):
        members.append({
            "chunk_id": meta.get("chunk_id", "rx"),
            "chunk_type": "table_row",
            "content": content,
            "distance": dist,
            "metadata_json": json.dumps(meta),
        })
    head = dict(members[0])
    head["_grouped_table"] = True
    head["_grouped_items"] = members
    head["distance"] = max(distances)
    return head


def test_format_grouped_table_row_basic_output():
    """Grouped table render includes header, location, table_id, matched rows, and tip."""
    meta1 = {"chunk_id": "r1", "table_id": "tbl1", "row_index": 1, "total_rows": 2,
              "breadcrumb_path": "Features", "sibling_ids": [], "sibling_previews": []}
    meta2 = {"chunk_id": "r2", "table_id": "tbl1", "row_index": 2, "total_rows": 2,
              "breadcrumb_path": "Features", "sibling_ids": [], "sibling_previews": []}
    result = _make_grouped_table_result([meta1, meta2], ["Col: a.", "Col: b."], [0.8, 0.85])
    text = _format_grouped_table_row(result)
    assert "Matched Table (2 of 2 rows):" in text
    assert "Location: Features" in text
    assert "Table ID: tbl1" in text
    assert "Matched rows:" in text
    assert "  [1] Col: a." in text
    assert "  [2] Col: b." in text
    assert "get_table_members(table_id='tbl1')" in text


def test_format_grouped_table_row_unmatched_previews():
    """Unmatched sibling rows appear under 'Other rows in table (not matched):'."""
    # r1 and r2 are matched; r3 is unmatched (only in sibling_ids of r1).
    meta1 = {"chunk_id": "r1", "table_id": "tbl1", "row_index": 1, "total_rows": 3,
              "breadcrumb_path": "Section",
              "sibling_ids": ["r2", "r3"], "sibling_previews": ["Row B", "Row C"]}
    meta2 = {"chunk_id": "r2", "table_id": "tbl1", "row_index": 2, "total_rows": 3,
              "breadcrumb_path": "Section",
              "sibling_ids": ["r1", "r3"], "sibling_previews": ["Row A", "Row C"]}
    result = _make_grouped_table_result([meta1, meta2], ["Row A", "Row B"], [0.8, 0.85])
    text = _format_grouped_table_row(result)
    assert "Matched Table (2 of 3 rows):" in text
    assert "Other rows in table (not matched):" in text
    assert "  - Row C" in text
    # Matched rows should NOT appear in unmatched section
    assert text.count("Row A") == 1  # only in matched rows
    assert text.count("Row B") == 1  # only in matched rows


def test_format_grouped_table_row_no_unmatched_previews():
    """When all sibling_previews belong to matched members, no unmatched section appears."""
    meta1 = {"chunk_id": "r1", "table_id": "tbl1", "row_index": 1, "total_rows": 2,
              "sibling_ids": ["r2"], "sibling_previews": ["Row B"]}
    meta2 = {"chunk_id": "r2", "table_id": "tbl1", "row_index": 2, "total_rows": 2,
              "sibling_ids": ["r1"], "sibling_previews": ["Row A"]}
    result = _make_grouped_table_result([meta1, meta2], ["Row A", "Row B"], [0.8, 0.85])
    text = _format_grouped_table_row(result)
    assert "Other rows in table (not matched):" not in text


def test_format_grouped_table_row_no_breadcrumb():
    """When breadcrumb_path is absent, no Location line is emitted."""
    meta1 = {"chunk_id": "r1", "table_id": "tbl2", "row_index": 1, "total_rows": 1,
              "sibling_ids": [], "sibling_previews": []}
    result = _make_grouped_table_result([meta1], ["Row A"], [0.7])
    # single-member grouped slot (manually forced)
    result["_grouped_table"] = True
    result["_grouped_items"] = [
        {"chunk_id": "r1", "chunk_type": "table_row", "content": "Row A",
         "distance": 0.7, "metadata_json": json.dumps(meta1)}
    ]
    text = _format_grouped_table_row(result)
    assert "Location:" not in text
    assert "Table ID: tbl2" in text


# ---------------------------------------------------------------------------
# End-to-end: grouped table rows render correctly in search_docs
# ---------------------------------------------------------------------------

@patch('opencrane.mcp.server.get_embeddings_service')
@patch('opencrane.mcp.server.get_milvus_service')
@pytest.mark.anyio
async def test_search_docs_groups_table_rows(mock_milvus_get, mock_embeddings_get, monkeypatch):
    """End-to-end: two table_row hits with same table_id render as one grouped result."""
    import opencrane.mcp.server as server_module

    server_module._chunk_index = None
    monkeypatch.setattr(server_module, "_build_chunk_index", lambda: {})

    mock_embeddings = Mock()
    mock_model = Mock()
    mock_model.encode.return_value = [[0.1] * 768]
    mock_embeddings.model = mock_model
    mock_embeddings_get.return_value = mock_embeddings

    mock_milvus = Mock()
    mock_milvus.search.return_value = [
        {"chunk_id": "r1", "content": "Name: foo. Value: 1.",
         "source_file": "table.md", "chunk_type": "table_row",
         "metadata_json": json.dumps({"table_id": "TBL", "row_index": 1,
                                      "total_rows": 2,
                                      "breadcrumb_path": "Config table",
                                      "sibling_ids": ["r2"],
                                      "sibling_previews": ["Name: bar. Value: 2."]}),
         "distance": 0.7},
        {"chunk_id": "r2", "content": "Name: bar. Value: 2.",
         "source_file": "table.md", "chunk_type": "table_row",
         "metadata_json": json.dumps({"table_id": "TBL", "row_index": 2,
                                      "total_rows": 2,
                                      "breadcrumb_path": "Config table",
                                      "sibling_ids": ["r1"],
                                      "sibling_previews": ["Name: foo. Value: 1."]}),
         "distance": 0.75},
    ]
    mock_milvus_get.return_value = mock_milvus

    results = await server_module._search_documentation_impl({
        "query": "config values", "limit": 5, "search_mode": "semantic",
    })
    # Should collapse to a single result slot
    assert len(results) == 1
    text = results[0].text
    assert "Matched Table (2 of 2 rows)" in text
    assert "Location: Config table" in text
    assert "[1] Name: foo. Value: 1." in text
    assert "[2] Name: bar. Value: 2." in text
    assert "Table ID: TBL" in text
    assert "get_table_members(table_id='TBL')" in text


@patch('opencrane.mcp.server.get_embeddings_service')
@patch('opencrane.mcp.server.get_milvus_service')
@pytest.mark.anyio
async def test_search_docs_grouped_table_rows_show_unmatched(mock_milvus_get, mock_embeddings_get,
                                                              monkeypatch):
    """End-to-end: grouped table slot lists unmatched sibling rows under their own header."""
    import opencrane.mcp.server as server_module

    server_module._chunk_index = None
    monkeypatch.setattr(server_module, "_build_chunk_index", lambda: {})

    mock_embeddings = Mock()
    mock_model = Mock()
    mock_model.encode.return_value = [[0.1] * 768]
    mock_embeddings.model = mock_model
    mock_embeddings_get.return_value = mock_embeddings

    mock_milvus = Mock()
    # Two hits (r1, r2) on a 3-row table; r3 is unmatched.
    mock_milvus.search.return_value = [
        {"chunk_id": "r1", "content": "Row A", "source_file": "t.md",
         "chunk_type": "table_row", "distance": 0.8,
         "metadata_json": json.dumps({"table_id": "TBL", "row_index": 1,
                                      "total_rows": 3,
                                      "sibling_ids": ["r2", "r3"],
                                      "sibling_previews": ["Row B", "Row C"]})},
        {"chunk_id": "r2", "content": "Row B", "source_file": "t.md",
         "chunk_type": "table_row", "distance": 0.85,
         "metadata_json": json.dumps({"table_id": "TBL", "row_index": 2,
                                      "total_rows": 3,
                                      "sibling_ids": ["r1", "r3"],
                                      "sibling_previews": ["Row A", "Row C"]})},
    ]
    mock_milvus_get.return_value = mock_milvus

    results = await server_module._search_documentation_impl({
        "query": "rows", "limit": 5, "search_mode": "semantic",
    })
    text = results[0].text
    assert "Matched Table (2 of 3 rows)" in text
    assert "Other rows in table (not matched):" in text
    assert "  - Row C" in text


# ---------------------------------------------------------------------------
# get_table_members: breadcrumb prefix stripping
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_get_table_members_strips_breadcrumb_prefix(monkeypatch):
    """get_table_members strips the leading '# {breadcrumb}\\n' for readable display."""
    breadcrumb = "Section > Subsection"
    index = {
        "r1": {
            "chunk_id": "r1", "chunk_type": "table_row",
            "content": f"# {breadcrumb}\nA: x. B: y.",
            "metadata": {"table_id": "t2", "row_index": 1, "breadcrumb_path": breadcrumb},
        },
    }
    monkeypatch.setattr(server, "_build_chunk_index", lambda: index)
    result = await server.get_table_members({"table_id": "t2"})
    text = result[0].text
    # Prefix must be stripped — the raw "# Section > Subsection" header must not appear
    assert f"# {breadcrumb}" not in text
    # The row body must still be present
    assert "A: x. B: y." in text


@pytest.mark.anyio
async def test_get_table_members_no_strip_when_no_breadcrumb(monkeypatch):
    """When content has no breadcrumb prefix, get_table_members emits content as-is (false branch)."""
    index = {
        "r1": {
            "chunk_id": "r1", "chunk_type": "table_row",
            "content": "A: x. B: y.",
            "metadata": {"table_id": "t3", "row_index": 1},
        },
    }
    monkeypatch.setattr(server, "_build_chunk_index", lambda: index)
    result = await server.get_table_members({"table_id": "t3"})
    text = result[0].text
    assert "A: x. B: y." in text


# ---------------------------------------------------------------------------
# _format_grouped_table_row: breadcrumb prefix stripping
# ---------------------------------------------------------------------------

def test_format_grouped_table_row_strips_breadcrumb_prefix():
    """_format_grouped_table_row strips the leading '# {breadcrumb}\\n' from each row content."""
    breadcrumb = "Features > Details"
    content_with_prefix = f"# {breadcrumb}\nCol: value."
    meta1 = {"chunk_id": "r1", "table_id": "tbl3", "row_index": 1, "total_rows": 2,
              "breadcrumb_path": breadcrumb, "sibling_ids": ["r2"], "sibling_previews": ["Row B"]}
    meta2 = {"chunk_id": "r2", "table_id": "tbl3", "row_index": 2, "total_rows": 2,
              "breadcrumb_path": breadcrumb, "sibling_ids": ["r1"], "sibling_previews": ["Row A"]}
    result = _make_grouped_table_result(
        [meta1, meta2],
        [content_with_prefix, "Col: other."],
        [0.8, 0.85],
    )
    text = _format_grouped_table_row(result)
    # Breadcrumb prefix must be stripped from the matched row display
    assert f"# {breadcrumb}" not in text
    # Row body must remain
    assert "Col: value." in text
    assert "Col: other." in text


def test_format_grouped_table_row_no_strip_when_content_has_no_prefix():
    """When content does not start with '# {breadcrumb}\\n', it is shown as-is (false branch)."""
    breadcrumb = "Features > Details"
    meta1 = {"chunk_id": "r1", "table_id": "tbl4", "row_index": 1, "total_rows": 1,
              "breadcrumb_path": breadcrumb, "sibling_ids": [], "sibling_previews": []}
    result = _make_grouped_table_result([meta1], ["Plain content, no prefix."], [0.7])
    result["_grouped_table"] = True
    result["_grouped_items"] = [
        {"chunk_id": "r1", "chunk_type": "table_row",
         "content": "Plain content, no prefix.", "distance": 0.7,
         "metadata_json": json.dumps(meta1)}
    ]
    text = _format_grouped_table_row(result)
    assert "Plain content, no prefix." in text
