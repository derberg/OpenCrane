"""Grouped list/table results and the member tools cite their source like a normal result."""

import json
from unittest.mock import Mock

import pytest

from opencrane.mcp import server

URL = "https://docs.example.com/troubleshooting#vpp-operator-log-level"
BREADCRUMB = "General Troubleshooting > Check logs > VPP Operator log level"


def _list_hit(chunk_id, position, content, source_url=URL, distance=0.7):
    meta = {"list_id": "LID", "position": position, "total_siblings": 2,
            "list_style": "unordered", "breadcrumb_path": BREADCRUMB}
    if source_url:
        meta["source_url"] = source_url
    return {"chunk_id": chunk_id, "content": f"# {BREADCRUMB}\n{content}",
            "source_file": "fpp/troubleshooting.md", "source_name": "fpp-docs",
            "chunk_type": "list_item", "metadata_json": json.dumps(meta),
            "distance": distance}


def _table_hit(chunk_id, row_index, content, source_url=URL, distance=0.7):
    meta = {"table_id": "TBL", "row_index": row_index, "total_rows": 2,
            "breadcrumb_path": BREADCRUMB}
    if source_url:
        meta["source_url"] = source_url
    return {"chunk_id": chunk_id, "content": content,
            "source_file": "fpp/troubleshooting.md", "source_name": "fpp-docs",
            "chunk_type": "table_row", "metadata_json": json.dumps(meta),
            "distance": distance}


def _milvus_members(members_by_value):
    """Milvus service mock whose query_by_field returns the rows for a value."""
    svc = Mock()
    svc.query_by_field.side_effect = lambda field, value, chunk_type=None, limit=16384: [
        r for r in members_by_value.get(value, [])
        if chunk_type is None or r.get("chunk_type") == chunk_type
    ]
    return svc


async def _search(monkeypatch, hits):
    embeddings = Mock()
    embeddings.model.encode.return_value = [[0.1] * 768]
    milvus = Mock()
    milvus.search.return_value = hits
    monkeypatch.setattr(server, "get_embeddings_service", lambda: embeddings)
    monkeypatch.setattr(server, "get_milvus_service", lambda: milvus)
    return await server._search_documentation_impl(
        {"query": "verbose VPP API call logging", "limit": 5, "search_mode": "semantic"}
    )


@pytest.mark.anyio
async def test_grouped_list_result_shows_source_and_source_name(monkeypatch):
    results = await _search(monkeypatch, [
        _list_hit("i1", 1, "**FPP_TRACE_API_CALLS** - displays API calls"),
        _list_hit("i2", 2, "**FPP_LOG_LEVEL** - sets the log level", distance=0.75),
    ])
    assert len(results) == 1
    lines = results[0].text.splitlines()
    assert lines[:4] == [
        "Result 1:",
        "Matched List (2 of 2 items):",
        f"Source: {URL}",
        "Source Name: fpp-docs",
    ]


@pytest.mark.anyio
async def test_grouped_table_result_shows_source_and_source_name(monkeypatch):
    results = await _search(monkeypatch, [
        _table_hit("r1", 1, "Variable: FPP_TRACE_API_CALLS. Default: off."),
        _table_hit("r2", 2, "Variable: FPP_LOG_LEVEL. Default: info.", distance=0.75),
    ])
    assert len(results) == 1
    lines = results[0].text.splitlines()
    assert lines[:4] == [
        "Result 1:",
        "Matched Table (2 of 2 rows):",
        f"Source: {URL}",
        "Source Name: fpp-docs",
    ]


@pytest.mark.anyio
async def test_grouped_and_single_results_cite_the_same_source(monkeypatch):
    """A grouped slot derives its source exactly like a normal result does."""
    single = await _search(monkeypatch, [_list_hit("i1", 1, "Only item")])
    grouped = await _search(monkeypatch, [
        _list_hit("i1", 1, "Only item"), _list_hit("i2", 2, "Second item"),
    ])

    def source_lines(text):
        return [line for line in text.splitlines() if line.startswith("Source")]

    assert source_lines(single[0].text) == source_lines(grouped[0].text)


def test_grouped_list_source_falls_back_to_url_in_content():
    head = _list_hit("i1", 1, "See https://docs.example.com/page for details", source_url=None)
    result = dict(head, _grouped=True, _grouped_items=[head, _list_hit("i2", 2, "B", source_url=None)])
    text = server._format_grouped_list_item(result)
    assert "Source: https://docs.example.com/page\n" in text


def test_grouped_table_source_falls_back_to_source_file():
    head = _table_hit("r1", 1, "Col: a.", source_url=None)
    head["source_name"] = ""
    result = dict(head, _grouped_table=True, _grouped_items=[head, _table_hit("r2", 2, "Col: b.", source_url=None)])
    text = server._format_grouped_table_row(result)
    assert "Source: fpp/troubleshooting.md\n" in text
    assert "Source Name:" not in text


@pytest.mark.anyio
async def test_get_list_members_shows_source(monkeypatch):
    monkeypatch.setattr(server, "get_milvus_service", lambda: _milvus_members({
        "LID": [_list_hit("i1", 1, "First"), _list_hit("i2", 2, "Second")],
    }))
    text = (await server.get_list_members({"list_id": "LID"}))[0].text
    lines = text.splitlines()
    assert lines[:3] == [
        "List (2 of 2 items, style=unordered)",
        f"Source: {URL}",
        "Source Name: fpp-docs",
    ]
    assert "[1] First" in text


@pytest.mark.anyio
async def test_get_table_members_shows_source(monkeypatch):
    monkeypatch.setattr(server, "get_milvus_service", lambda: _milvus_members({
        "TBL": [_table_hit("r1", 1, "Col: a."), _table_hit("r2", 2, "Col: b.")],
    }))
    text = (await server.get_table_members({"table_id": "TBL"}))[0].text
    lines = text.splitlines()
    assert lines[:3] == [f"Source: {URL}", "Source Name: fpp-docs", ""]
    assert "Col: a." in text
    assert "Col: b." in text


@pytest.mark.anyio
async def test_get_table_members_source_falls_back_to_source_file(monkeypatch):
    monkeypatch.setattr(server, "get_milvus_service", lambda: _milvus_members({
        "TBL": [_table_hit("r1", 1, "Col: a.", source_url=None)],
    }))
    text = (await server.get_table_members({"table_id": "TBL"}))[0].text
    assert text.startswith("Source: fpp/troubleshooting.md\n")
