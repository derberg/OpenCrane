"""End-to-end integration test for the middleware allowed-sources override.

Proves that ``set_allowed_sources`` (the value a project-supplied middleware sets
via ``OpenCraneConfig.middleware``) actually constrains ``search_docs`` results
against a REAL Milvus Lite store — not just the unit-level contextvar/policy
wiring covered elsewhere.

Two sources are indexed (``source-a`` and ``source-b``), each with a unique
token in its content. The real MCP ``search_docs`` tool is invoked through
``call_tool`` while the per-request allowed-sources override is set, and the
returned results are checked against what the override should permit.

Run with: pytest tests/integration/test_middleware_authz_integration.py -m integration
Requires milvus-lite (pip install pymilvus[milvus_lite]).
"""

import pytest

pytestmark = pytest.mark.integration

from opencrane.mcp.server import call_tool
from opencrane.mcp.services.embeddings import EmbeddingService
from opencrane.mcp.services.milvus_client import MilvusService
from opencrane.mcp.auth.runtime import reset_auth_runtime, set_allowed_sources
from opencrane.shared.models.vector_chunk import VectorChunk


ALPHA = "ALPHATOKENUNIQUE"
BETA = "BETATOKENUNIQUE"


@pytest.fixture
def two_source_index(tmp_path, monkeypatch):
    """Index one chunk under ``source-a`` and one under ``source-b`` in a temp DB."""
    db_path = tmp_path / "milvus.db"
    monkeypatch.setenv("MILVUS_DB_PATH", str(db_path))

    embedder = EmbeddingService()
    milvus = MilvusService()
    milvus.create_collection()

    def _vc(chunk_id, content, source_name, source_file):
        return VectorChunk(
            chunk_id=chunk_id,
            embedding=embedder.model.encode([content])[0].tolist(),
            content=content,
            source_file=source_file,
            source_name=source_name,
            chunk_type="prose",
            metadata_json="{}",
            token_count=10,
            line_start=1,
        )

    milvus.insert_chunks([
        _vc("authz_a", f"Installation and configuration guide {ALPHA} for the service.",
            "source-a", "source-a/install.md"),
        _vc("authz_b", f"Installation and configuration guide {BETA} for the service.",
            "source-b", "source-b/install.md"),
    ])
    milvus.client.flush(milvus.collection_name)
    milvus.load_collection()

    reset_auth_runtime()
    yield
    reset_auth_runtime()


async def _search_text():
    results = await call_tool("search_docs", {
        "query": "installation and configuration guide",
        "search_mode": "semantic",
        "limit": 10,
    })
    return "\n".join(r.text for r in results)


@pytest.mark.anyio
async def test_no_override_returns_both_sources(two_source_index):
    """With no middleware override, the existing access policy allows both sources."""
    text = await _search_text()
    assert ALPHA in text
    assert BETA in text


@pytest.mark.anyio
async def test_allowed_sources_restricts_to_subset(two_source_index):
    """set_allowed_sources(("source-a",)) restricts results to source-a only."""
    set_allowed_sources(("source-a",))
    text = await _search_text()
    assert ALPHA in text, "source-a content must be present"
    assert BETA not in text, "source-b content must be filtered out"


@pytest.mark.anyio
async def test_empty_allowed_sources_short_circuits_to_no_results(two_source_index):
    """An empty allowed set returns zero results — never disables the filter."""
    set_allowed_sources(())
    text = await _search_text()
    assert ALPHA not in text
    assert BETA not in text


@pytest.fixture
def two_source_lookup_index(tmp_path, monkeypatch):
    """Index a YAML chunk, a list and a table under each of two sources."""
    import json

    monkeypatch.setenv("MILVUS_DB_PATH", str(tmp_path / "milvus.db"))
    embedder = EmbeddingService()
    milvus = MilvusService()
    milvus.create_collection()
    vector = embedder.model.encode(["lookup"])[0].tolist()

    def _vc(chunk_id, source, chunk_type, content, metadata, **ids):
        return VectorChunk(
            chunk_id=chunk_id, embedding=vector, content=content,
            source_file=f"{source}/doc.md", source_name=source, chunk_type=chunk_type,
            metadata_json=json.dumps(metadata), token_count=5, line_start=1, **ids,
        )

    chunks = []
    for source, token in (("source-a", ALPHA), ("source-b", BETA)):
        chunks += [
            _vc(f"yaml_{source}", source, "crd_definition", json.dumps({"kind": token}), {}),
            _vc(f"li_{source}", source, "list_item", f"item {token}", {"position": 1},
                list_id=f"list-{source}"),
            _vc(f"tr_{source}", source, "table_row", f"row {token}", {"row_index": 0},
                table_id=f"table-{source}"),
        ]
    milvus.insert_chunks(chunks)
    milvus.client.flush(milvus.collection_name)
    milvus.load_collection()

    reset_auth_runtime()
    yield
    reset_auth_runtime()


async def _lookup_texts():
    calls = [
        ("get_yaml_definition", "chunk_id", "yaml_source-{}"),
        ("get_list_members", "list_id", "list-source-{}"),
        ("get_table_members", "table_id", "table-source-{}"),
    ]
    texts = {}
    for tool, key, pattern in calls:
        for side in ("a", "b"):
            results = await call_tool(tool, {key: pattern.format(side)})
            texts[(tool, side)] = "\n".join(r.text for r in results)
    return texts


@pytest.mark.anyio
async def test_lookup_tools_without_override_return_both_sources(two_source_lookup_index):
    texts = await _lookup_texts()
    for tool in ("get_yaml_definition", "get_list_members", "get_table_members"):
        assert ALPHA in texts[(tool, "a")]
        assert BETA in texts[(tool, "b")]


@pytest.mark.anyio
async def test_lookup_tools_hide_sources_outside_allowed_sources(two_source_lookup_index):
    """The source filter works against real Milvus: source-b ids read as missing."""
    set_allowed_sources(("source-a",))
    texts = await _lookup_texts()
    for tool in ("get_yaml_definition", "get_list_members", "get_table_members"):
        assert ALPHA in texts[(tool, "a")]
        assert BETA not in texts[(tool, "b")]
    assert texts[("get_yaml_definition", "b")] == "Chunk not found: yaml_source-b"
    assert texts[("get_list_members", "b")] == "No list found for list_id='list-source-b'."
    assert texts[("get_table_members", "b")] == "No table found for table_id='table-source-b'."
