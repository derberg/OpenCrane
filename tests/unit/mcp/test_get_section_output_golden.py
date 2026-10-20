"""Golden test: the exact text ``get_section`` returns for a page with lists and a table.

Renders ``get_section`` from the chunks in
``tests/fixtures/get_section_output/chunks.json`` and compares each output with
the matching file in ``expected/``. See the fixture README for details.

REGEN mode
----------
Set REGEN=1 to rewrite the ``expected/`` files from the current output:

    REGEN=1 ./pytest.sh tests/unit/mcp/test_get_section_output_golden.py --no-cov -v

Review the diff of ``expected/`` before you commit it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from opencrane.mcp import server

_FIXTURE_DIR = Path(__file__).parent.parent.parent / "fixtures" / "get_section_output"
_EXPECTED_DIR = _FIXTURE_DIR / "expected"

# Metadata keys the index lifts into their own scalar columns.
_COLUMNS = ("list_id", "table_id", "clause_id", "parent_chunk_id")


def _rows() -> dict[str, dict]:
    """Fixture chunks as Milvus rows (``metadata`` serialized to ``metadata_json``)."""
    chunks = json.loads((_FIXTURE_DIR / "chunks.json").read_text())
    rows = {}
    for chunk in chunks:
        row = {k: v for k, v in chunk.items() if k != "metadata"}
        row["metadata_json"] = json.dumps(chunk["metadata"])
        for column in _COLUMNS:
            value = chunk["metadata"].get(column)
            row[column] = value if isinstance(value, str) else ""
        rows[chunk["chunk_id"]] = row
    return rows


class _Milvus:
    """In-memory stand-in for the Milvus lookups the section tools use."""

    def __init__(self, rows: dict[str, dict]):
        self.rows = rows

    def _match(self, row, chunk_type):
        return chunk_type is None or row["chunk_type"] == chunk_type

    def get_chunk(self, chunk_id):
        row = self.rows.get(chunk_id)
        return dict(row) if row else None

    def query_by_field(self, field, value, chunk_type=None, limit=16384, source_names=None):
        return [dict(r) for r in self.rows.values() if r.get(field) == value and self._match(r, chunk_type)]

    def query_by_values(self, field, values, chunk_type=None, limit=16384):
        return [dict(r) for r in self.rows.values() if r.get(field) in values and self._match(r, chunk_type)]

    def query_by_prefix(self, field, prefix, chunk_type=None, limit=16384):
        return [dict(r) for r in self.rows.values()
                if (r.get(field) or "").startswith(prefix) and self._match(r, chunk_type)]


# expected file -> get_section arguments
CASES = {
    "get_section_upgrade.txt": {"chunk_id": "upgrade"},
    "get_section_upgrade_with_subsections.txt": {"chunk_id": "upgrade", "include_subsections": True},
    "get_section_from_table_row.txt": {"chunk_id": "log-var-1"},
}


@pytest.mark.anyio
@pytest.mark.parametrize("expected_name", sorted(CASES))
async def test_get_section_output_matches_golden_file(monkeypatch, expected_name):
    milvus = _Milvus(_rows())
    monkeypatch.setattr(server, "get_milvus_service", lambda: milvus)
    results = await server.get_section(CASES[expected_name])
    actual = "\n---\n".join(r.text for r in results)
    expected_path = _EXPECTED_DIR / expected_name

    if os.environ.get("REGEN"):
        expected_path.write_text(actual)
        return

    assert actual == expected_path.read_text(), (
        f"Output differs from {expected_path.name}. Run with REGEN=1 to update expected files."
    )
