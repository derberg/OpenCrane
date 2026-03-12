"""Test edge cases in hybrid search mode."""
import pytest
from unittest.mock import patch
from opencrane.mcp import server as mcp_server


@pytest.mark.anyio
@patch('opencrane.mcp.server.get_keyword_service')
@patch('opencrane.mcp.server.get_milvus_service')
@patch('opencrane.mcp.server.get_embeddings_service')
async def test__search_documentation_impl_hybrid_missing_chunk_record(
    mock_get_embed, mock_get_milvus, mock_get_keyword, monkeypatch
):
    """Test hybrid search when a chunk_id is None (missing record)."""
    class DummyEmbeddings:
        class DummyModel:
            def encode(self, queries, batch_size=None, show_progress_bar=False):
                return [[0.5] * 768 for _ in queries]
        model = DummyModel()

    class DummyMilvus:
        def search(self, vector, limit=5, categories=None, chunk_types=None, metadata_contains=None):
            return [
                {
                    "chunk_id": "valid1",
                    "content": "valid semantic",
                    "source_file": "sem.md",
                    "chunk_type": "prose",
                    "metadata_json": "{}",
                    "distance": 0.9,
                },
                {
                    "chunk_id": None,  # Invalid - should be skipped
                    "content": "",
                    "source_file": "",
                    "chunk_type": "",
                    "metadata_json": "{}",
                    "distance": 0.8,
                }
            ]

    class DummyKeyword:
        def search(self, query, limit=5, categories=None, chunk_types=None, metadata_contains=None):
            return [
                {
                    "chunk_id": "valid2",
                    "content": "valid keyword",
                    "source_file": "key.md",
                    "chunk_type": "prose",
                    "metadata_json": "{}",
                    "distance": 0.85,
                }
            ]

    mock_get_embed.return_value = DummyEmbeddings()
    mock_get_milvus.return_value = DummyMilvus()
    mock_get_keyword.return_value = DummyKeyword()
    monkeypatch.setattr(mcp_server, "_build_chunk_source_map", lambda: {})

    res = await mcp_server._search_documentation_impl({
        "query": "test",
        "search_mode": "hybrid",
        "limit": 5,
        "categories": ["product"],
    })

    # Should return 2 valid results (None chunk_id is skipped)
    assert len(res) == 2
    assert "valid1" in res[0].text or "valid2" in res[0].text
    assert "valid1" in res[1].text or "valid2" in res[1].text
