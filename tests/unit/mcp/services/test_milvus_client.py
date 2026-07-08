"""Unit tests for MilvusService."""

import pytest
from unittest.mock import Mock, patch, ANY, call
from opencrane.mcp.services.milvus_client import MilvusService
from opencrane.shared.models.vector_chunk import VectorChunk


class TestMilvusService:
    """Test cases for MilvusService."""

    @patch.dict('os.environ', {'MILVUS_DB_PATH': '/tmp/milvus_test.db'})
    @patch('opencrane.mcp.services.milvus_client.MilvusClient')
    def test_init_with_env_uri(self, mock_client_class):
        """Test initialization with MILVUS_DB_PATH environment variable."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        service = MilvusService()

        assert service.uri == '/tmp/milvus_test.db'
        mock_client_class.assert_called_once_with(uri='/tmp/milvus_test.db')

    @patch('opencrane.mcp.services.milvus_client.MilvusClient')
    def test_init_connection_failure(self, mock_client_class):
        """Test handling of connection failure."""
        mock_client_class.side_effect = Exception("Connection failed")

        with pytest.raises(Exception, match="Connection failed"):
            MilvusService("localhost", 19530, "test_collection")

    @patch('opencrane.mcp.services.milvus_client.MilvusClient')
    def test_create_collection(self, mock_client_class):
        """Test creating collection with schema."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        service = MilvusService()
        service.create_collection()

        # Verify create_schema was called
        mock_client.create_schema.assert_called_once()
        # Verify add_field calls for all fields
        schema_mock = mock_client.create_schema.return_value
        expected_calls = [
            call(field_name='chunk_id', datatype=ANY, max_length=64, is_primary=True),
            call(field_name='embedding', datatype=ANY, dim=768),
            call(field_name='content', datatype=ANY, max_length=65535),
            call(field_name='source_file', datatype=ANY, max_length=512),
            call(field_name='source_name', datatype=ANY, max_length=256),
            call(field_name='chunk_type', datatype=ANY, max_length=32),
            call(field_name='metadata_json', datatype=ANY, max_length=65535),
            call(field_name='token_count', datatype=ANY),
            call(field_name='line_start', datatype=ANY),
            call(field_name='list_id', datatype=ANY, max_length=64),
            call(field_name='table_id', datatype=ANY, max_length=64),
        ]
        schema_mock.add_field.assert_has_calls(expected_calls, any_order=True)
        assert schema_mock.add_field.call_count == 11  # All fields added
        # Verify index params: the embedding vector index plus scalar indexes on
        # the member-lookup fields.
        index_params_mock = mock_client.prepare_index_params.return_value
        index_params_mock.add_index.assert_any_call(
            field_name="embedding",
            index_type="AUTOINDEX",
            metric_type="COSINE"
        )
        index_params_mock.add_index.assert_any_call(field_name="list_id", index_type="INVERTED")
        index_params_mock.add_index.assert_any_call(field_name="table_id", index_type="INVERTED")
        assert index_params_mock.add_index.call_count == 3
        # Verify create_collection was called
        mock_client.create_collection.assert_called_once_with(
            collection_name=service.collection_name,
            schema=schema_mock,
            index_params=index_params_mock
        )

    @patch('opencrane.mcp.services.milvus_client.MilvusClient')
    def test_load_collection_failure(self, mock_client_class):
        """Test handling of collection load failure."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.load_collection.side_effect = Exception("Load failed")

        service = MilvusService()

        with pytest.raises(Exception, match="Load failed"):
            service.load_collection()

    @patch('opencrane.mcp.services.milvus_client.MilvusClient')
    def test_load_collection(self, mock_client_class):
        """Test loading collection."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        service = MilvusService()
        service.load_collection()

        mock_client.load_collection.assert_called_once_with(
            collection_name=service.collection_name
        )

    @patch('opencrane.mcp.services.milvus_client.MilvusClient')
    def test_insert_chunks_failure(self, mock_client_class):
        """Test handling of insert failure."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.insert.side_effect = Exception("Insert failed")

        service = MilvusService()
        chunks = [
            VectorChunk(
                chunk_id="id1",
                embedding=[0.1] * 768,
                content="content1",
                source_file="file1.md",
                chunk_type="prose",
                metadata_json='{"key": "value"}',
                token_count=10,
                line_start=1
            )
        ]

        with pytest.raises(Exception, match="Insert failed"):
            service.insert_chunks(chunks)

    @patch('opencrane.mcp.services.milvus_client.MilvusClient')
    def test_insert_chunks(self, mock_client_class):
        """Test inserting vector chunks."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        service = MilvusService()
        chunks = [
            VectorChunk(
                chunk_id="id1",
                embedding=[0.1] * 768,
                content="content1",
                source_file="file1.md",
                chunk_type="list_item",
                metadata_json='{"key": "value"}',
                token_count=10,
                line_start=1,
                list_id="L1",
            )
        ]

        service.insert_chunks(chunks)

        mock_client.insert.assert_called_once()
        call_args = mock_client.insert.call_args
        assert call_args[1]['collection_name'] == service.collection_name
        assert len(call_args[1]['data']) == 1
        row = call_args[1]['data'][0]
        assert row['chunk_id'] == "id1"
        # list_id/table_id are lifted into their own columns (empty string when absent)
        assert row['list_id'] == "L1"
        assert row['table_id'] == ""

    @patch('opencrane.mcp.services.milvus_client.MilvusClient')
    def test_search_without_filter(self, mock_client_class):
        """Test search without chunk type filter."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.search.return_value = [[
            {"chunk_id": "1", "content": "test", "source_file": "a.md", "chunk_type": "prose", "metadata_json": "{}", "distance": 0.9},
            {"chunk_id": "2", "content": "test2", "source_file": "b.md", "chunk_type": "code", "metadata_json": "{}", "distance": 0.8}
        ]]

        service = MilvusService()
        results = service.search([0.1] * 768, limit=5)

        mock_client.search.assert_called_once()
        call_kwargs = mock_client.search.call_args[1]
        assert call_kwargs['collection_name'] == service.collection_name
        assert call_kwargs['data'] == [[0.1] * 768]
        assert call_kwargs['limit'] == 5
        assert call_kwargs['filter'] is None
        assert call_kwargs['output_fields'] == ["chunk_id", "content", "source_file", "source_name", "chunk_type", "metadata_json", "token_count", "line_start"]
        assert len(results) == 2
        assert call_kwargs['search_params'] == {"metric_type": "COSINE", "params": {}}

    @patch('opencrane.mcp.services.milvus_client.MilvusClient')
    def test_search_with_filter(self, mock_client_class):
        """Test search with chunk type filter."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.search.return_value = [["result1"]]

        service = MilvusService()
        results = service.search([0.1] * 768, limit=3, chunk_types=["prose", "code"])

        call_kwargs = mock_client.search.call_args[1]
        assert call_kwargs['filter'] == '(chunk_type == "prose" || chunk_type == "code")'
        assert call_kwargs['limit'] == 3
        assert len(results) == 1

    @patch('opencrane.mcp.services.milvus_client.MilvusClient')
    def test_search_with_source_file_filter(self, mock_client_class):
        """Test search with source file filter expression."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.search.return_value = [[
            {"chunk_id": "1", "content": "test", "source_file": "a.md", "chunk_type": "prose", "metadata_json": "{}", "distance": 0.9}
        ]]

        service = MilvusService()
        results = service.search([0.1] * 768, limit=2, source_files=["a.md", "b.md"])

        call_kwargs = mock_client.search.call_args[1]
        assert call_kwargs['filter'] == '(source_file == "a.md" || source_file == "b.md")'
        assert len(results) == 1

    @patch('opencrane.mcp.services.milvus_client.MilvusClient')
    def test_search_with_source_name_filter(self, mock_client_class):
        """source_names filter is rendered as OR-clause and combined with other filters via AND."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.search.return_value = [[
            {"chunk_id": "1", "source_name": "Org/repo", "metadata_json": "{}", "distance": 0.9}
        ]]

        service = MilvusService()
        service.search([0.0] * 768, limit=2, source_names=["Org/repo", "Org/other"])

        call_kwargs = mock_client.search.call_args[1]
        assert call_kwargs['filter'] == '(source_name == "Org/repo" || source_name == "Org/other")'

    @patch('opencrane.mcp.services.milvus_client.MilvusClient')
    def test_search_with_both_filters(self, mock_client_class):
        """Test search with both chunk_types and source_files combined with AND."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.search.return_value = [[
            {"chunk_id": "1", "content": "test", "source_file": "a.md", "chunk_type": "prose", "metadata_json": "{}", "distance": 0.9}
        ]]

        service = MilvusService()
        results = service.search([0.1] * 768, limit=2, chunk_types=["prose"], source_files=["a.md"]) 

        call_kwargs = mock_client.search.call_args[1]
        assert call_kwargs['filter'] == '(chunk_type == "prose") && (source_file == "a.md")'
        assert len(results) == 1

    @patch('opencrane.mcp.services.milvus_client.MilvusClient')
    def test_search_metadata_contains_filters_client_side(self, mock_client_class):
        """Test metadata_contains post-filtering reduces result set."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        # Simulate two hits with metadata_json
        mock_client.search.return_value = [[
            {"chunk_id": "1", "metadata_json": '{"a": "x", "b": "y"}'},
            {"chunk_id": "2", "metadata_json": '{"a": "x"}'},
        ]]

        service = MilvusService()
        results = service.search([0.0] * 768, limit=10, metadata_contains=['"b": "y"'])
        assert len(results) == 1
        assert results[0]["chunk_id"] == "1"

    @patch('opencrane.mcp.services.milvus_client.MilvusClient')
    def test_search_failure(self, mock_client_class):
        """Test handling of search failure returns empty list."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.search.side_effect = Exception("Search failed")

        service = MilvusService()
        results = service.search([0.1] * 768)
        
        # Should return empty list on error instead of raising
        assert results == []

    @patch('opencrane.mcp.services.milvus_client.MilvusClient')
    def test_get_collection_stats_failure(self, mock_client_class):
        """Test handling of stats retrieval failure."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.get_collection_stats.side_effect = Exception("Stats failed")

        service = MilvusService()

        with pytest.raises(Exception, match="Stats failed"):
            service.get_collection_stats()

    @patch('opencrane.mcp.services.milvus_client.MilvusClient')
    def test_get_collection_stats(self, mock_client_class):
        """Test getting collection statistics."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.get_collection_stats.return_value = {"row_count": 100}

        service = MilvusService()
        stats = service.get_collection_stats()

        mock_client.get_collection_stats.assert_called_once_with(
            collection_name=service.collection_name
        )
        assert stats == {"row_count": 100}

    @patch('opencrane.mcp.services.milvus_client.MilvusClient')
    def test_insert_chunks_with_large_content(self, mock_client_class):
        """Test inserting chunks with content that needs truncation."""
        from opencrane.shared.models.vector_chunk import VectorChunk
        
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        service = MilvusService()
        
        # Create chunk with very large content (>65KB)
        large_content = "x" * 70000
        chunks = [
            VectorChunk(
                chunk_id="test1",
                embedding=[0.1] * 768,
                content=large_content,
                source_file="test.md",
                chunk_type="prose",
                metadata_json='{}',
                token_count=100,
                line_start=1
            )
        ]
        
        service.insert_chunks(chunks)
        
        # Verify insert was called
        mock_client.insert.assert_called_once()
        inserted_data = mock_client.insert.call_args[1]['data']
        
        # Content should be truncated
        assert len(inserted_data[0]['content']) < 70000
        assert "Content truncated" in inserted_data[0]['content']

    @patch('opencrane.mcp.services.milvus_client.MilvusClient')
    def test_insert_chunks_with_large_metadata(self, mock_client_class):
        """Test inserting chunks with metadata that needs truncation."""
        from opencrane.shared.models.vector_chunk import VectorChunk
        
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        service = MilvusService()
        
        # Create chunk with very large metadata (>65KB)
        large_metadata = '{"data": "' + ("x" * 70000) + '"}'
        chunks = [
            VectorChunk(
                chunk_id="test1",
                embedding=[0.1] * 768,
                content="test",
                source_file="test.md",
                chunk_type="prose",
                metadata_json=large_metadata,
                token_count=100,
                line_start=1
            )
        ]
        
        service.insert_chunks(chunks)
        
        # Verify insert was called
        mock_client.insert.assert_called_once()
        inserted_data = mock_client.insert.call_args[1]['data']
        
        # Metadata should be truncated
        assert len(inserted_data[0]['metadata_json']) < 70000
        assert "truncated" in inserted_data[0]['metadata_json']

    @patch('opencrane.mcp.services.milvus_client.MilvusClient')
    def test_create_collection_failure(self, mock_client_class):
        """Test handling of collection creation failure."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.create_collection.side_effect = Exception("Creation failed")

        service = MilvusService()

        with pytest.raises(Exception, match="Creation failed"):
            service.create_collection()

    @patch.dict('os.environ', {'MILVUS_DB_PATH': ''})
    @patch('opencrane.mcp.services.milvus_client.MilvusClient')
    def test_init_server_mode_uses_host_and_port(self, mock_client_class):
        """When MILVUS_DB_PATH is empty, fall back to host/port server-mode URI."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        service = MilvusService(host="myhost", port=12345, collection_name="coll")

        assert service.host == "myhost"
        assert service.port == 12345
        assert service.uri == "http://myhost:12345"
        mock_client_class.assert_called_once_with(uri="http://myhost:12345")

    @patch('opencrane.mcp.services.milvus_client.MilvusClient')
    def test_get_chunk_found(self, mock_client_class):
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.get.return_value = [{"chunk_id": "c1", "content": "hi"}]

        service = MilvusService()
        assert service.get_chunk("c1") == {"chunk_id": "c1", "content": "hi"}
        mock_client.get.assert_called_once()

    @patch('opencrane.mcp.services.milvus_client.MilvusClient')
    def test_get_chunk_missing_returns_none(self, mock_client_class):
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.get.return_value = []

        service = MilvusService()
        assert service.get_chunk("nope") is None

    @patch('opencrane.mcp.services.milvus_client.MilvusClient')
    def test_get_chunk_error_returns_none(self, mock_client_class):
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.get.side_effect = Exception("boom")

        service = MilvusService()
        assert service.get_chunk("c1") is None

    @patch('opencrane.mcp.services.milvus_client.MilvusClient')
    def test_query_by_field(self, mock_client_class):
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.query.return_value = [{"chunk_id": "r1"}, {"chunk_id": "r2"}]

        service = MilvusService()
        rows = service.query_by_field("list_id", "L1")
        assert [r["chunk_id"] for r in rows] == ["r1", "r2"]
        # Sanitized value interpolated into the filter (Milvus Lite has no templating).
        assert mock_client.query.call_args[1]["filter"] == 'list_id == "L1"'

    @patch('opencrane.mcp.services.milvus_client.MilvusClient')
    def test_query_by_field_with_chunk_type(self, mock_client_class):
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.query.return_value = []

        service = MilvusService()
        service.query_by_field("list_id", "L1", chunk_type="list_item")
        assert mock_client.query.call_args[1]["filter"] == 'list_id == "L1" and chunk_type == "list_item"'

    @patch('opencrane.mcp.services.milvus_client.MilvusClient')
    def test_query_by_field_sanitizes_value(self, mock_client_class):
        """A value with filter-breaking characters is stripped before interpolation."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.query.return_value = []

        service = MilvusService()
        service.query_by_field("list_id", 'a" or "1"=="1')
        # Quotes/spaces/= removed → cannot break out of or inject the filter.
        assert mock_client.query.call_args[1]["filter"] == 'list_id == "aor11"'

    @patch('opencrane.mcp.services.milvus_client.MilvusClient')
    def test_query_by_field_warns_on_row_cap(self, mock_client_class):
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.query.return_value = [{"chunk_id": "r"}, {"chunk_id": "r"}]

        service = MilvusService()
        # limit == number of rows returned -> the "hit the cap" warning branch
        rows = service.query_by_field("list_id", "L1", limit=2)
        assert len(rows) == 2

    @patch('opencrane.mcp.services.milvus_client.MilvusClient')
    def test_query_by_field_error_returns_empty(self, mock_client_class):
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.query.side_effect = Exception("boom")

        service = MilvusService()
        assert service.query_by_field("list_id", "L1") == []

    @patch('opencrane.mcp.services.milvus_client.MilvusClient')
    def test_field_names(self, mock_client_class):
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.describe_collection.return_value = {
            "fields": [{"name": "chunk_id"}, {"name": "list_id"}, {"name": "table_id"}]
        }

        service = MilvusService()
        assert service.field_names() == {"chunk_id", "list_id", "table_id"}

    @patch('opencrane.mcp.services.milvus_client.MilvusClient')
    def test_field_names_error_returns_empty(self, mock_client_class):
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.describe_collection.side_effect = Exception("boom")

        service = MilvusService()
        assert service.field_names() == set()


class TestTruncateMetadata:
    """The metadata truncator must always emit valid JSON within the field limit."""

    def test_within_limit_passes_through(self):
        from opencrane.mcp.services.milvus_client import _truncate_metadata
        meta = '{"source_url": "https://example.com"}'
        assert _truncate_metadata(meta) == meta

    def test_drops_heavy_fields_to_fit(self):
        from opencrane.mcp.services.milvus_client import _truncate_metadata, MAX_METADATA_LENGTH
        import json as _json
        big_neighbors = ["n" * 100 for _ in range(2000)]  # far over the limit
        meta = _json.dumps({"source_url": "u", "neighbor_chunks": big_neighbors})
        assert len(meta) > MAX_METADATA_LENGTH
        out = _truncate_metadata(meta)
        parsed = _json.loads(out)  # must be valid JSON
        assert parsed["source_url"] == "u"
        assert parsed["truncated"] is True
        assert "neighbor_chunks" not in parsed
        assert len(out) <= MAX_METADATA_LENGTH

    def test_falls_back_to_scalars_only(self):
        from opencrane.mcp.services.milvus_client import _truncate_metadata, MAX_METADATA_LENGTH
        import json as _json
        # A single non-heavy list field that alone overflows the limit.
        meta = _json.dumps({"src": "u", "other_list": ["x" * 100 for _ in range(2000)]})
        assert len(meta) > MAX_METADATA_LENGTH
        out = _truncate_metadata(meta)
        parsed = _json.loads(out)
        assert parsed["src"] == "u"
        assert "other_list" not in parsed  # dropped by the scalar-only fallback
        assert len(out) <= MAX_METADATA_LENGTH

    def test_invalid_json_yields_minimal_marker(self):
        from opencrane.mcp.services.milvus_client import _truncate_metadata, MAX_METADATA_LENGTH
        junk = "x" * (MAX_METADATA_LENGTH + 10)  # over-limit and not JSON
        assert _truncate_metadata(junk) == '{"truncated": true}'

    def test_scalar_value_still_too_large_yields_minimal(self):
        from opencrane.mcp.services.milvus_client import _truncate_metadata, MAX_METADATA_LENGTH
        import json as _json
        # A single scalar string that itself exceeds the limit — even scalar-only can't fit.
        meta = _json.dumps({"huge": "y" * (MAX_METADATA_LENGTH + 10)})
        assert _truncate_metadata(meta) == '{"truncated": true}'