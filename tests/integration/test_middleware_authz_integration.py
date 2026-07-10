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
