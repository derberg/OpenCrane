"""End-to-end test for list-item chunking.

Runs the full pipeline against the ``01_simple_ordered.md`` fixture:
FileProcessor → embeddings → Milvus Lite → MCP ``search_docs`` → grouping.

Verifies the acceptance promised in ``tests/fixtures/lists/README.md``:

- both list items end up in the top-K for an obvious query
- MCP collapses the two sibling hits into a single grouped result slot
- the grouped slot contains both item bodies and the shared ``list_id``
- ``get_list_members(list_id)`` re-fetches all items of the list in order
"""

import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

from opencrane.mcp import server as mcp_server
from opencrane.mcp.collection_meta import write_chunk_types
from opencrane.mcp.services.embeddings import EmbeddingService
from opencrane.mcp.services.milvus_client import MilvusService
from opencrane.rag.services.chunk_serializer import ChunkSerializer
from opencrane.rag.services.file_processor import FileProcessor
from opencrane.shared.models.vector_chunk import VectorChunk


FIXTURE = Path("tests/fixtures/lists/01_simple_ordered.md")


@pytest.fixture
def list_item_index(tmp_path, monkeypatch):
    """Chunk, embed, and index the ordered-list fixture into a throwaway Milvus Lite DB."""
    assert FIXTURE.exists(), f"Missing fixture: {FIXTURE}"

    chunks_path = tmp_path / "chunks.json"
    db_path = tmp_path / "milvus.db"

    monkeypatch.setenv("AI_DOCS_CHUNKS_FILE", str(chunks_path))
    monkeypatch.setenv("MILVUS_DB_PATH", str(db_path))
    monkeypatch.setenv("AI_DOCS_COLLECTION_META_FILE", str(tmp_path / "collection_meta.json"))

    # 1. Chunk
    chunks = FileProcessor().process_file(FIXTURE)
    ChunkSerializer.serialize_chunks(chunks, chunks_path)

    # 2. Embed + insert into temp Milvus Lite (mirrors the real index step:
    #    list_id/table_id lifted into columns, chunk-type sidecar written).
    embedder = EmbeddingService()
    milvus = MilvusService()
    milvus.create_collection()

    vector_chunks = []
    for chunk in chunks:
        content_str = chunk.content if isinstance(chunk.content, str) else json.dumps(chunk.content)
        vec = embedder.model.encode([content_str])[0].tolist()
        vector_chunks.append(VectorChunk(
            chunk_id=chunk.chunk_id,
            embedding=vec,
            content=content_str,
            source_file=chunk.source_file,
            chunk_type=chunk.chunk_type,
            metadata_json=json.dumps(chunk.metadata) if chunk.metadata else "{}",
            token_count=chunk.token_count,
            line_start=chunk.line_start or 0,
            list_id=(chunk.metadata or {}).get("list_id"),
            table_id=(chunk.metadata or {}).get("table_id"),
        ))
    milvus.insert_chunks(vector_chunks)
    milvus.client.flush(milvus.collection_name)
    milvus.load_collection()
    write_chunk_types(c.chunk_type for c in chunks)

    return chunks


@pytest.mark.anyio
async def test_chunks_include_list_items_with_shared_list_id(list_item_index):
    """End-to-end chunking produces list_item chunks with the expected metadata."""
    chunks = list_item_index
    list_items = [c for c in chunks if c.chunk_type == "list_item"]
    assert len(list_items) == 2, f"Expected 2 list_item chunks, got {len(list_items)}"

    # Siblings share a list_id
    list_ids = {c.metadata["list_id"] for c in list_items}
    assert len(list_ids) == 1, f"Expected shared list_id, got {list_ids}"

    # Each carries the full required metadata surface
    required = {
        "breadcrumb_path", "list_id", "list_style", "position",
        "total_siblings", "sibling_ids", "sibling_previews",
        "parent_item_id", "depth",
    }
    for item in list_items:
        assert required.issubset(item.metadata.keys())
        assert item.metadata["list_style"] == "ordered"
        assert item.metadata["total_siblings"] == 2
        assert item.metadata["parent_item_id"] is None
        assert item.metadata["depth"] == 0

    positions = sorted(c.metadata["position"] for c in list_items)
    assert positions == [1, 2]


@pytest.mark.anyio
async def test_search_docs_groups_sibling_list_items(list_item_index):
    """Two hits on the same list_id must collapse into one grouped MCP result slot."""
    from opencrane.mcp.server import call_tool

    results = await call_tool("search_docs", {
        "query": "install cgw helm chart 1.7",
        "search_mode": "semantic",
        "limit": 5,
    })

    # search_docs emits one TextContent per result slot; grouping collapses
    # the two sibling list_item hits into a single slot, so with 4 indexed
    # chunks (2 list_item + 2 prose) we expect 3 slots.
    assert len(results) == 3, (
        f"Expected 3 result slots (2 prose + 1 grouped list), got {len(results)}.\n"
        + "\n---\n".join(r.text for r in results)
    )
    full_text = "\n".join(r.text for r in results)

    # Exactly one grouped "Matched List" block across all slots
    grouped_blocks = full_text.count("Matched List (")
    assert grouped_blocks == 1, (
        f"Expected exactly 1 grouped list block, got {grouped_blocks}. Output:\n{full_text}"
    )

    # Both item bodies inline inside the grouped slot
    assert "cgw Helm chart" in full_text, f"Missing item 1 body:\n{full_text}"
    assert "cgw-support Helm chart" in full_text, f"Missing item 2 body:\n{full_text}"

    # Grouped slot advertises list_id and the get_list_members follow-up tool
    assert "List ID:" in full_text
    assert "get_list_members(list_id=" in full_text

    # No standalone list_item slot — every list_item hit must be inside the grouped slot
    assert "Type: list_item" not in full_text, (
        f"list_item chunk leaked into a non-grouped slot:\n{full_text}"
    )


@pytest.mark.anyio
async def test_get_list_members_returns_full_list_in_order(list_item_index):
    """get_list_members(list_id) returns every item of the list ordered by position."""
    from opencrane.mcp.server import call_tool

    # Pull any indexed list_item's list_id directly from our chunked output
    list_item = next(c for c in list_item_index if c.chunk_type == "list_item")
    list_id = list_item.metadata["list_id"]

    results = await call_tool("get_list_members", {"list_id": list_id})
    assert len(results) == 1
    body = results[0].text

    # Both items in the list appear, item 1 before item 2
    idx_item1 = body.find("cgw Helm chart")
    idx_item2 = body.find("cgw-support Helm chart")
    assert idx_item1 != -1 and idx_item2 != -1, f"Both items must be returned:\n{body}"
    assert idx_item1 < idx_item2, f"Items must be ordered by position:\n{body}"


@pytest.mark.anyio
async def test_list_item_tools_are_exposed_when_index_has_list_items(list_item_index):
    """get_list_members must be listed when the index contains list_item chunks."""
    from opencrane.mcp.server import list_tools

    tools = await list_tools()
    names = {t.name for t in tools}
    assert "get_list_members" in names, f"get_list_members missing from exposed tools: {names}"
    # get_metadata_schema gains a chunk_type parameter when list_item is present
    schema_tool = next(t for t in tools if t.name == "get_metadata_schema")
    assert "chunk_type" in (schema_tool.inputSchema.get("properties") or {})
