"""The MCP tools show a list's lead-in sentence once, not on every item."""

import json
from unittest.mock import Mock, patch

import pytest

from opencrane.mcp.server import _format_grouped_list_item, _own_item_text, get_list_members


def _list_row(chunk_id, content, metadata):
    return {"chunk_id": chunk_id, "content": content, "chunk_type": "list_item",
            "metadata_json": json.dumps(metadata)}


def _milvus_members(members_by_value):
    svc = Mock()
    svc.query_by_field.side_effect = lambda field, value, chunk_type=None, limit=16384: list(
        members_by_value.get(value, [])
    )
    return svc


META = {"list_id": "lx", "list_style": "ordered", "position": 1, "depth": 0,
        "total_siblings": 2, "breadcrumb_path": "Install > CLI",
        "list_caption": "To install the extension using CLI:"}
META2 = {**META, "position": 2}
FIRST = "# Install > CLI\nTo install the extension using CLI:\n1. Create a file."
SECOND = "# Install > CLI\nTo install the extension using CLI:\n2. Apply it."


@patch('opencrane.mcp.server.get_milvus_service')
@pytest.mark.anyio
async def test_get_list_members_shows_lead_in_once(mock_get_milvus):
    mock_get_milvus.return_value = _milvus_members({"lx": [_list_row("i1", FIRST, META), _list_row("i2", SECOND, META2)]})
    text = (await get_list_members({"list_id": "lx"}))[0].text
    assert text.count("To install the extension using CLI:") == 1
    assert "Lead-in: To install the extension using CLI:" in text
    assert "[1] 1. Create a file." in text
    assert "[2] 2. Apply it." in text


def test_grouped_search_result_shows_lead_in_once():
    members = [
        {**_list_row("i1", FIRST, META), "distance": 0.9},
        {**_list_row("i2", SECOND, META2), "distance": 0.8},
    ]
    text = _format_grouped_list_item({"_grouped_items": members})
    assert text.count("To install the extension using CLI:") == 1
    assert "[1] 1. Create a file." in text


def test_section_item_text_drops_lead_in():
    top = {"content": FIRST, "metadata": META}
    nested = {"content": "# Install > CLI\nTo install the extension using CLI:\n1. Create a file.\nchild detail",
              "metadata": {**META, "depth": 1}}
    assert _own_item_text(top, "Install > CLI") == "1. Create a file."
    assert _own_item_text(nested, "Install > CLI") == "child detail"
