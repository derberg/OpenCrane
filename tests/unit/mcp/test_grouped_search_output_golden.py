"""Golden test: the exact text the MCP tools return for grouped lists and tables.

Renders ``search_docs`` (grouped list, grouped table, grouped list without a
``source_url``), ``get_list_members`` and ``get_table_members`` from the chunks
in ``tests/fixtures/grouped_search_output/chunks.json`` and compares each output
with the matching file in ``expected/``. See the fixture README for details.

REGEN mode
----------
Set REGEN=1 to rewrite the ``expected/`` files from the current output:

    REGEN=1 ./pytest.sh tests/unit/mcp/test_grouped_search_output_golden.py --no-cov -v

Review the diff of ``expected/`` before you commit it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from opencrane.mcp import server

_FIXTURE_DIR = Path(__file__).parent.parent.parent / "fixtures" / "grouped_search_output"
_EXPECTED_DIR = _FIXTURE_DIR / "expected"


def _rows() -> dict[str, dict]:
    """Fixture chunks as Milvus rows (``metadata`` serialized to ``metadata_json``)."""
    chunks = json.loads((_FIXTURE_DIR / "chunks.json").read_text())
    rows = {}
    for chunk in chunks:
        row = {k: v for k, v in chunk.items() if k != "metadata"}
        row["metadata_json"] = json.dumps(chunk["metadata"])
        rows[chunk["chunk_id"]] = row
    return rows


def _milvus(hits: list[dict], rows: dict[str, dict]) -> Mock:
    """Milvus mock: ``search`` returns the hits, ``query_by_field`` the members."""
    milvus = Mock()
    milvus.search.return_value = hits

    def query_by_field(field, value, chunk_type=None, limit=16384):
        return [
            dict(r) for r in rows.values()
            if json.loads(r["metadata_json"]).get(field) == value
            and (chunk_type is None or r["chunk_type"] == chunk_type)
        ]

    milvus.query_by_field.side_effect = query_by_field
    return milvus


async def _search(monkeypatch, rows, hit_ids):
    # Scores fall with rank, so the hits keep the order given here.
    hits = [dict(rows[cid], distance=0.9 - 0.05 * i) for i, cid in enumerate(hit_ids)]
    embeddings = Mock()
    embeddings.model.encode.return_value = [[0.1] * 768]
    monkeypatch.setattr(server, "get_embeddings_service", lambda: embeddings)
    monkeypatch.setattr(server, "get_milvus_service", lambda: _milvus(hits, rows))
    return await server._search_documentation_impl(
        {"query": "gateway", "limit": 5, "search_mode": "semantic"}
    )


async def _members(monkeypatch, rows, tool, arguments):
    monkeypatch.setattr(server, "get_milvus_service", lambda: _milvus([], rows))
    return await tool(arguments)


# expected file -> coroutine factory that renders it
CASES = {
    "search_docs_grouped_list.txt":
        lambda mp, rows: _search(mp, rows, ["upgrade-step-1", "upgrade-step-3"]),
    "search_docs_grouped_table.txt":
        lambda mp, rows: _search(mp, rows, ["log-level-row-2", "log-level-row-1"]),
    "search_docs_grouped_list_without_source_url.txt":
        lambda mp, rows: _search(mp, rows, ["prereq-1", "prereq-2"]),
    "get_list_members.txt":
        lambda mp, rows: _members(mp, rows, server.get_list_members, {"list_id": "upgrade-1-7"}),
    "get_table_members.txt":
        lambda mp, rows: _members(mp, rows, server.get_table_members, {"table_id": "log-settings"}),
}


@pytest.mark.anyio
@pytest.mark.parametrize("expected_name", sorted(CASES))
async def test_grouped_output_matches_golden_file(monkeypatch, expected_name):
    results = await CASES[expected_name](monkeypatch, _rows())
    actual = "\n---\n".join(r.text for r in results)
    expected_path = _EXPECTED_DIR / expected_name

    if os.environ.get("REGEN"):
        expected_path.write_text(actual)
        return

    assert actual == expected_path.read_text(), (
        f"Output differs from {expected_path.name}. Run with REGEN=1 to update expected files."
    )
