"""Integration tests: search filter values cannot inject Milvus filter logic.

``search_docs`` passes ``chunk_types`` and the authorized ``source_names`` into
one Milvus boolean filter. A value that closes the quoted literal could OR in
its own clause and lift the source restriction. These tests run against a REAL
Milvus Lite store with two sources and prove that a caller restricted to
``source-a`` can never read ``source-b``, whatever the filter values contain.

Run with: ./pytest.sh tests/integration/test_search_filter_injection.py
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
QUERY = "installation and configuration guide"

# Closes the chunk_type literal and ORs in a clause that matches every row.
# Because && binds tighter than ||, the source clause no longer applies.
TYPE_INJECTION = 'prose") || (chunk_type != "'
NAME_INJECTION = 'source-a") || (source_name != "'
FILE_INJECTION = 'x" || source_file != "y") || (source_file != "'


@pytest.fixture
def two_source_index(tmp_path, monkeypatch):
    """Index one chunk under ``source-a`` and one under ``source-b`` in a temp DB."""
    db_path = tmp_path / "milvus.db"
    monkeypatch.setenv("MILVUS_DB_PATH", str(db_path))
    monkeypatch.setenv("MAPPING_FILE", str(tmp_path / "missing-config.yaml"))

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
        _vc("inj_a", f"Installation and configuration guide {ALPHA} for the service.",
            "source-a", "source-a/install.md"),
        _vc("inj_b", f"Installation and configuration guide {BETA} for the service.",
            "source-b", "source-b/install.md"),
    ])
    milvus.client.flush(milvus.collection_name)
    milvus.load_collection()

    reset_auth_runtime()
    yield milvus, embedder
    reset_auth_runtime()


async def _search_text(**extra):
    results = await call_tool("search_docs", {
        "query": QUERY,
        "search_mode": "semantic",
        "limit": 10,
        **extra,
    })
    return "\n".join(r.text for r in results)


@pytest.mark.anyio
async def test_chunk_types_injection_cannot_reach_disallowed_source(two_source_index):
    """An injected chunk_types value is rejected and never reaches source-b."""
    set_allowed_sources(("source-a",))
    text = await _search_text(chunk_types=[TYPE_INJECTION])
    assert BETA not in text, "chunk_types injection bypassed the source policy"
    assert text.startswith("Error: invalid chunk_types")


@pytest.mark.anyio
async def test_source_names_injection_cannot_reach_disallowed_source(two_source_index):
    """An injected source_names value is rejected and never reaches source-b."""
    set_allowed_sources(("source-a",))
    text = await _search_text(source_names=[NAME_INJECTION])
    assert BETA not in text
    assert text.startswith("Error: invalid source_names")


@pytest.mark.anyio
async def test_valid_filters_still_return_allowed_source(two_source_index):
    """Well-formed chunk_types and source_names still search normally."""
    set_allowed_sources(("source-a",))
    text = await _search_text(chunk_types=["prose"], source_names=["source-a"])
    assert ALPHA in text
    assert BETA not in text


@pytest.mark.parametrize("kwargs", [
    {"chunk_types": [TYPE_INJECTION], "source_names": ["source-a"]},
    {"source_names": [NAME_INJECTION]},
    {"source_files": [FILE_INJECTION], "source_names": ["source-a"]},
])
def test_milvus_search_values_cannot_widen_filter(two_source_index, kwargs):
    """MilvusService.search itself never lets a filter value widen the result set."""
    milvus, embedder = two_source_index
    vector = embedder.model.encode([QUERY])[0].tolist()
    hits = milvus.search(vector, limit=10, **kwargs)
    assert not any(BETA in h["content"] for h in hits)
