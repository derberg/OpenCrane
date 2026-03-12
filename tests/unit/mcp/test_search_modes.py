import asyncio
import pytest
from unittest.mock import Mock, patch

from opencrane.mcp import server as mcp_server


@pytest.mark.anyio
@patch('opencrane.mcp.server.get_keyword_service')
async def test__search_documentation_impl_keyword_mode(mock_get_keyword, monkeypatch):
    class DummyKeyword:
        def search(self, query, limit=5, categories=None, chunk_types=None, source_files=None, metadata_contains=None):
            return [{
                "chunk_id": "k1",
                "content": "keyword content",
                "source_file": "doc.md",
                "chunk_type": "prose",
                "metadata_json": "{}",
                "distance": 3.14,
            }]

    mock_get_keyword.return_value = DummyKeyword()

    # Avoid loading large maps in test
    monkeypatch.setattr(mcp_server, "_build_chunk_source_map", lambda: {})

    res = await mcp_server._search_documentation_impl({
        "query": "test",
        "search_mode": "keyword",
        "limit": 1,
        "categories": ["product"],
    })

    assert isinstance(res, list) and res
    assert res[0].type == "text"
    assert "Result 1:" in res[0].text
    assert "Score:" in res[0].text


@pytest.mark.anyio
@patch('opencrane.mcp.server.get_keyword_service')
@patch('opencrane.mcp.server.get_milvus_service')
@patch('opencrane.mcp.server.get_embeddings_service')
async def test__search_documentation_impl_hybrid_mode(mock_get_embed, mock_get_milvus, mock_get_keyword, monkeypatch):
    """Test hybrid search combining semantic and keyword results."""
    class DummyEmbeddings:
        class DummyModel:
            def encode(self, queries, batch_size=None, show_progress_bar=False):
                return [[0.5] * 768 for _ in queries]
        model = DummyModel()

    class DummyMilvus:
        def search(self, vector, limit=5, categories=None, chunk_types=None, metadata_contains=None):
            return [{
                "chunk_id": "sem1",
                "content": "semantic result",
                "source_file": "semantic.md",
                "chunk_type": "prose",
                "metadata_json": "{}",
                "distance": 0.95,
            }]

    class DummyKeyword:
        def search(self, query, limit=5, categories=None, chunk_types=None, metadata_contains=None):
            return [{
                "chunk_id": "key1",
                "content": "keyword result",
                "source_file": "keyword.md",
                "chunk_type": "code_snippet",
                "metadata_json": "{}",
                "distance": 0.85,
            }]

    mock_get_embed.return_value = DummyEmbeddings()
    mock_get_milvus.return_value = DummyMilvus()
    mock_get_keyword.return_value = DummyKeyword()
    monkeypatch.setattr(mcp_server, "_build_chunk_source_map", lambda: {})

    res = await mcp_server._search_documentation_impl({
        "query": "test hybrid",
        "search_mode": "hybrid",
        "limit": 5,
        "alpha": 0.7,
        "categories": ["product"],
    })

    assert isinstance(res, list)
    assert len(res) == 2
    assert "Result 1:" in res[0].text or "Result 1:" in res[1].text


@pytest.mark.anyio
async def test__search_documentation_impl_invalid_mode(monkeypatch):
    """Test that invalid search mode returns error message."""
    class DummyEmbeddings:
        class DummyModel:
            def encode(self, queries, batch_size=None, show_progress_bar=False):
                return [[0.5] * 768 for _ in queries]
        model = DummyModel()

    monkeypatch.setattr(mcp_server, "get_embeddings_service", lambda: DummyEmbeddings())
    monkeypatch.setattr(mcp_server, "_build_chunk_source_map", lambda: {})

    res = await mcp_server._search_documentation_impl({
        "query": "test",
        "search_mode": "invalid_mode",
        "categories": ["product"],
    })

    assert len(res) == 1
    assert "Invalid search_mode" in res[0].text


@pytest.mark.anyio
@patch('opencrane.mcp.server.get_keyword_service')
@patch('opencrane.mcp.server.get_milvus_service')
@patch('opencrane.mcp.server.get_embeddings_service')
async def test__search_documentation_impl_hybrid_empty_results(mock_get_embed, mock_get_milvus, mock_get_keyword, monkeypatch):
    """Test hybrid search with no results."""
    class DummyEmbeddings:
        class DummyModel:
            def encode(self, queries, batch_size=None, show_progress_bar=False):
                return [[0.5] * 768 for _ in queries]
        model = DummyModel()

    class DummyMilvus:
        def search(self, vector, limit=5, categories=None, chunk_types=None, metadata_contains=None):
            return []

    class DummyKeyword:
        def search(self, query, limit=5, categories=None, chunk_types=None, metadata_contains=None):
            return []

    mock_get_embed.return_value = DummyEmbeddings()
    mock_get_milvus.return_value = DummyMilvus()
    mock_get_keyword.return_value = DummyKeyword()
    monkeypatch.setattr(mcp_server, "_build_chunk_source_map", lambda: {})

    res = await mcp_server._search_documentation_impl({
        "query": "test empty",
        "search_mode": "hybrid",
        "limit": 5,
        "categories": ["product"],
    })

    assert len(res) == 1
    assert res[0].text == "No results found."


@pytest.mark.anyio
@patch('opencrane.mcp.server.get_milvus_service')
@patch('opencrane.mcp.server.get_embeddings_service')
async def test__search_documentation_impl_semantic_none_results(mock_get_embed, mock_get_milvus, monkeypatch):
    """Test semantic search when service returns None."""
    class DummyEmbeddings:
        class DummyModel:
            def encode(self, queries, batch_size=None, show_progress_bar=False):
                return [[0.5] * 768 for _ in queries]
        model = DummyModel()

    class DummyMilvus:
        def search(self, vector, limit=5, categories=None, chunk_types=None, metadata_contains=None):
            return None  # Simulate error returning None

    mock_get_embed.return_value = DummyEmbeddings()
    mock_get_milvus.return_value = DummyMilvus()
    monkeypatch.setattr(mcp_server, "_build_chunk_source_map", lambda: {})

    res = await mcp_server._search_documentation_impl({
        "query": "test",
        "search_mode": "semantic",
        "limit": 5,
        "categories": ["product"],
    })

    assert len(res) == 1
    assert res[0].text == "No results found."


@pytest.mark.anyio
@patch('opencrane.mcp.server.get_keyword_service')
async def test__search_documentation_impl_keyword_none_results(mock_get_keyword, monkeypatch):
    """Test keyword search when service returns None."""
    class DummyKeyword:
        def search(self, query, limit=5, categories=None, chunk_types=None, metadata_contains=None):
            return None  # Simulate error returning None

    mock_get_keyword.return_value = DummyKeyword()
    monkeypatch.setattr(mcp_server, "_build_chunk_source_map", lambda: {})

    res = await mcp_server._search_documentation_impl({
        "query": "test",
        "search_mode": "keyword",
        "limit": 5,
        "categories": ["product"],
    })

    assert len(res) == 1
    assert res[0].text == "No results found."


@pytest.mark.anyio
@patch('opencrane.mcp.server.get_keyword_service')
@patch('opencrane.mcp.server.get_milvus_service')
@patch('opencrane.mcp.server.get_embeddings_service')
async def test__search_documentation_impl_hybrid_none_results(mock_get_embed, mock_get_milvus, mock_get_keyword, monkeypatch):
    """Test hybrid search when both services return None."""
    class DummyEmbeddings:
        class DummyModel:
            def encode(self, queries, batch_size=None, show_progress_bar=False):
                return [[0.5] * 768 for _ in queries]
        model = DummyModel()

    class DummyMilvus:
        def search(self, vector, limit=5, categories=None, chunk_types=None, metadata_contains=None):
            return None

    class DummyKeyword:
        def search(self, query, limit=5, categories=None, chunk_types=None, metadata_contains=None):
            return None

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

    assert len(res) == 1
    assert res[0].text == "No results found."


