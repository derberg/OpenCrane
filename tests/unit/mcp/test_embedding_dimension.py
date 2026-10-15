"""The vector dimension follows the embedding model instead of a fixed 768."""

from unittest.mock import MagicMock, Mock, patch, mock_open, ANY

import pytest

from opencrane.mcp.init_vector_db import _REQUIRED_FIELDS, main as init_main
from opencrane.mcp.services.milvus_client import MilvusService
from opencrane.shared.models.vector_chunk import DEFAULT_EMBEDDING_DIM

_CHUNKS = '[{"content": "test", "chunk_type": "prose", "source_file": "test.md", "token_count": 10, "line_start": 1, "metadata": {}}]'


def _describe(dim):
    return {"fields": [
        {"name": "chunk_id", "params": {"max_length": 64}},
        {"name": "embedding", "params": {"dim": dim}},
    ]}


@pytest.fixture
def service():
    with patch('opencrane.mcp.services.milvus_client.MilvusClient') as client_class:
        client_class.return_value = Mock()
        yield MilvusService()


class TestMilvusVectorDim:
    def test_create_collection_uses_given_dim(self, service):
        service.create_collection(dim=1024)
        schema = service.client.create_schema.return_value
        schema.add_field.assert_any_call(field_name="embedding", datatype=ANY, dim=1024)
        assert service.vector_dim() == 1024  # cached, no describe needed
        service.client.describe_collection.assert_not_called()

    def test_create_collection_default_dim_unchanged(self, service):
        service.create_collection()
        schema = service.client.create_schema.return_value
        schema.add_field.assert_any_call(field_name="embedding", datatype=ANY, dim=768)
        assert DEFAULT_EMBEDDING_DIM == 768

    def test_vector_dim_reads_schema_and_caches(self, service):
        service.client.describe_collection.return_value = _describe(384)
        assert service.vector_dim() == 384
        assert service.vector_dim() == 384
        service.client.describe_collection.assert_called_once()

    def test_vector_dim_none_without_embedding_field(self, service):
        service.client.describe_collection.return_value = {"fields": [{"name": "chunk_id"}]}
        assert service.vector_dim() is None

    def test_vector_dim_none_when_collection_missing(self, service):
        service.client.describe_collection.side_effect = Exception("collection not found")
        assert service.vector_dim() is None

    def test_search_rejects_mismatched_query_dim(self, service):
        service.client.describe_collection.return_value = _describe(1024)
        with pytest.raises(ValueError, match=r"768 dimensions.*1024-dimensional"):
            service.search([0.1] * 768, limit=5)
        service.client.search.assert_not_called()

    def test_search_accepts_matching_query_dim(self, service):
        service.client.describe_collection.return_value = _describe(1024)
        service.client.search.return_value = [[]]
        assert service.search([0.1] * 1024, limit=5) == []
        service.client.search.assert_called_once()


def _run_init(milvus, vectors, dimensions=768):
    with patch('opencrane.mcp.init_vector_db.setup_logging'), \
         patch('opencrane.mcp.init_vector_db.MilvusService', return_value=milvus), \
         patch('opencrane.mcp.init_vector_db.EmbeddingService') as emb_class, \
         patch('builtins.open', new_callable=mock_open, read_data=_CHUNKS), \
         patch('opencrane.mcp.init_vector_db.Path') as path:
        path.return_value.exists.return_value = True
        embeddings = MagicMock()
        embeddings.dimensions = dimensions
        embeddings.embeddings = [MagicMock(chunk_id="test_id", vector=v) for v in vectors]
        emb_class.return_value.load_embeddings.return_value = embeddings
        init_main()


class TestInitVectorDbDim:
    def test_new_collection_takes_dim_from_embeddings(self):
        milvus = MagicMock()
        milvus.client.has_collection.return_value = False
        _run_init(milvus, [[0.1] * 1024], dimensions=1024)
        milvus.create_collection.assert_called_once_with(dim=1024, embedding_metadata=ANY)

    def test_populated_collection_with_other_dim_is_rebuilt(self):
        milvus = MagicMock()
        milvus.client.has_collection.return_value = True
        milvus.field_names.return_value = set(_REQUIRED_FIELDS)
        milvus.get_collection_stats.return_value = {"row_count": 65}
        milvus.vector_dim.return_value = 768
        _run_init(milvus, [[0.1] * 384], dimensions=384)
        milvus.client.drop_collection.assert_called_once()
        milvus.create_collection.assert_called_once_with(dim=384, embedding_metadata=ANY)
        milvus.insert_chunks.assert_called_once()

    def test_populated_collection_with_same_dim_is_kept(self):
        milvus = MagicMock()
        milvus.client.has_collection.return_value = True
        milvus.field_names.return_value = set(_REQUIRED_FIELDS)
        milvus.get_collection_stats.return_value = {"row_count": 65}
        milvus.vector_dim.return_value = 1024
        _run_init(milvus, [[0.1] * 1024], dimensions=1024)
        milvus.client.drop_collection.assert_not_called()
        milvus.create_collection.assert_not_called()

    def test_empty_embeddings_use_recorded_dimensions(self):
        milvus = MagicMock()
        milvus.client.has_collection.return_value = False
        with patch('opencrane.mcp.init_vector_db.json.load', return_value=[]):
            _run_init(milvus, [], dimensions=1024)
        milvus.create_collection.assert_called_once_with(dim=1024, embedding_metadata=ANY)

    def test_empty_embeddings_without_dimensions_use_default(self):
        milvus = MagicMock()
        milvus.client.has_collection.return_value = False
        with patch('opencrane.mcp.init_vector_db.json.load', return_value=[]):
            _run_init(milvus, [], dimensions=0)
        milvus.create_collection.assert_called_once_with(dim=DEFAULT_EMBEDDING_DIM, embedding_metadata=ANY)


@pytest.mark.anyio
async def test_server_search_reports_dim_mismatch():
    """A model/index dimension mismatch surfaces as an error, not empty results."""
    from opencrane.mcp import server

    embeddings = MagicMock()
    embeddings.model.encode.return_value = [[0.1] * 768]
    with patch('opencrane.mcp.services.milvus_client.MilvusClient') as client_class:
        client_class.return_value = Mock()
        milvus = MilvusService()
    milvus.client.describe_collection.return_value = _describe(1024)
    with patch.object(server, 'get_embeddings_service', return_value=embeddings), \
         patch.object(server, 'get_milvus_service', return_value=milvus):
        out = await server._search_documentation_impl({"query": "q", "search_mode": "semantic"})
    assert "Search failed" in out[0].text
    assert "1024-dimensional" in out[0].text


def test_empty_embeddings_keep_populated_collection_of_other_dim():
    """An embeddings file without vectors says nothing about the model, so it
    must not count as a model change and wipe a populated collection."""
    milvus = MagicMock()
    milvus.client.has_collection.return_value = True
    milvus.field_names.return_value = set(_REQUIRED_FIELDS)
    milvus.get_collection_stats.return_value = {"row_count": 65}
    milvus.vector_dim.return_value = 1024
    with patch('opencrane.mcp.init_vector_db.json.load', return_value=[]):
        _run_init(milvus, [], dimensions=0)
    milvus.client.drop_collection.assert_not_called()
    milvus.create_collection.assert_not_called()
