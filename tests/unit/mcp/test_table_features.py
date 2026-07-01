"""Tests for table MCP features: get_table_members, search tip, metadata schema filter."""

import json
from unittest.mock import Mock, patch

import pytest

from opencrane.mcp import server


def test_get_table_members_orders_overview_then_rows(monkeypatch):
    index = {
        "o": {"chunk_id": "o", "chunk_type": "table", "content": "overview",
              "metadata": {"table_id": "t1", "columns": ["A"], "total_rows": 2}},
        "r2": {"chunk_id": "r2", "chunk_type": "table_row", "content": "A: b.",
               "metadata": {"table_id": "t1", "row_index": 2}},
        "r1": {"chunk_id": "r1", "chunk_type": "table_row", "content": "A: a.",
               "metadata": {"table_id": "t1", "row_index": 1}},
        "x": {"chunk_id": "x", "chunk_type": "prose", "content": "nope", "metadata": {}},
    }
    monkeypatch.setattr(server, "_build_chunk_index", lambda: index)
    members = server._get_table_members("t1")
    assert [m["chunk_id"] for m in members] == ["o", "r1", "r2"]


def test_has_table_row_chunks(monkeypatch):
    monkeypatch.setattr(server, "_get_indexed_chunk_types", lambda: {"table_row", "prose"})
    assert server._has_table_row_chunks() is True
    monkeypatch.setattr(server, "_get_indexed_chunk_types", lambda: {"prose"})
    assert server._has_table_row_chunks() is False


@pytest.mark.anyio
async def test_get_table_members_tool_formats_output(monkeypatch):
    """get_table_members tool returns overview then rows formatted as text."""
    index = {
        "o": {"chunk_id": "o", "chunk_type": "table", "content": "| A | B |\n|---|---|\n",
              "metadata": {"table_id": "t1", "columns": ["A", "B"], "total_rows": 1}},
        "r1": {"chunk_id": "r1", "chunk_type": "table_row", "content": "A: x. B: y.",
               "metadata": {"table_id": "t1", "row_index": 1}},
    }
    monkeypatch.setattr(server, "_build_chunk_index", lambda: index)
    result = await server.get_table_members({"table_id": "t1"})
    text = result[0].text
    assert "| A | B |" in text
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
@patch('opencrane.mcp.server._get_indexed_chunk_types', return_value={"prose", "table", "table_row"})
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
    server_module._chunk_source_map = None

    # No chunks.json needed since we monkeypatch the index and source map
    monkeypatch.setattr(server_module, "_build_chunk_index", lambda: {})
    monkeypatch.setattr(server_module, "_build_chunk_source_map", lambda: {})

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
