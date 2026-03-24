"""Integration tests for search functionality against real Milvus instance.

These tests run against an actual Milvus Lite database to catch issues
that mocks might miss (like data structure mismatches, API changes, etc.).

Run with: pytest tests/integration/test_search_integration.py -v -m integration

IMPORTANT: These tests require milvus-lite:
  - Run in Docker: docker exec <container-name> pytest tests/integration/test_search_integration.py -v -m integration
  - Or install: pip install pymilvus[milvus_lite]
"""

import pytest
import tempfile
import os
from pathlib import Path

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration

from opencrane.mcp.services.milvus_client import MilvusService
from opencrane.mcp.services.embeddings import EmbeddingService
from opencrane.mcp.services.keyword_search import KeywordSearchService
from opencrane.shared.models.vector_chunk import VectorChunk


@pytest.fixture
def temp_milvus_db():
    """Create a temporary Milvus Lite database for testing."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name

    # Set environment variable for Milvus Lite
    original_env = os.environ.get('MILVUS_DB_PATH')
    os.environ['MILVUS_DB_PATH'] = db_path

    yield db_path

    # Cleanup
    if original_env:
        os.environ['MILVUS_DB_PATH'] = original_env
    else:
        os.environ.pop('MILVUS_DB_PATH', None)

    # Remove temp file
    try:
        os.unlink(db_path)
    except:
        pass


@pytest.fixture
def milvus_with_test_data(temp_milvus_db):
    """Create Milvus instance and populate with test data."""
    service = MilvusService()

    # Create collection
    service.create_collection()

    # Create test chunks with embeddings
    embedding_service = EmbeddingService()

    test_chunks = [
        VectorChunk(
            chunk_id="integration_test_1",
            embedding=embedding_service.model.encode(["test content 1"])[0].tolist(),
            content="This is test content about UPF setup and testing procedures.",
            source_file="test1.md",
            chunk_type="prose",
            metadata_json='{"test": true}',
            token_count=15,
            line_start=1
        ),
        VectorChunk(
            chunk_id="integration_test_2",
            embedding=embedding_service.model.encode(["test content 2"])[0].tolist(),
            content="Another test chunk with different content about configuration.",
            source_file="test2.md",
            chunk_type="code_snippet",
            metadata_json='{"test": true}',
            token_count=12,
            line_start=10
        ),
        VectorChunk(
            chunk_id="integration_test_3",
            embedding=embedding_service.model.encode(["test content 3"])[0].tolist(),
            content="Third chunk for testing hybrid search with keywords.",
            source_file="test3.md",
            chunk_type="prose",
            metadata_json='{"test": true}',
            token_count=10,
            line_start=5
        )
    ]

    # Insert chunks
    service.insert_chunks(test_chunks)

    # Load collection
    service.load_collection()

    return service, test_chunks


@pytest.mark.integration
class TestSearchIntegration:
    """Integration tests that run against real Milvus instance."""

    def test_semantic_search_returns_flat_structure(self, milvus_with_test_data):
        """CRITICAL: Test that real Milvus returns properly flattened results.

        This is the test that would have caught the nested structure bug!
        """
        service, test_chunks = milvus_with_test_data

        # Get embedding for a query
        embedding_service = EmbeddingService()
        query_vec = embedding_service.model.encode(["UPF testing"])[0].tolist()

        # Search
        results = service.search(query_vec, limit=3)

        # Verify we got results
        assert len(results) > 0, "Should return at least one result"

        # CRITICAL CHECKS: Verify flat structure
        for i, result in enumerate(results):
            # Must have chunk_id at TOP LEVEL (not nested)
            assert 'chunk_id' in result, f"Result {i} missing chunk_id at top level"
            assert result['chunk_id'] is not None, f"Result {i} has None chunk_id"
            assert result['chunk_id'] != '', f"Result {i} has empty chunk_id"

            # Must have content at TOP LEVEL
            assert 'content' in result, f"Result {i} missing content at top level"
            assert result['content'] is not None, f"Result {i} has None content"
            assert isinstance(result['content'], str), f"Result {i} content is not string"

            # Must have all required fields at TOP LEVEL
            required = ['source_file', 'chunk_type', 'metadata_json', 'distance']
            for field in required:
                assert field in result, f"Result {i} missing {field} at top level"

            # Must NOT have nested 'entity' structure
            assert 'entity' not in result, f"Result {i} has nested 'entity' - not flattened!"

            print(f"✓ Result {i}: chunk_id={result['chunk_id']}, type={type(result)}")

    def test_search_with_chunk_type_filter(self, milvus_with_test_data):
        """Test chunk type filtering."""
        service, _ = milvus_with_test_data

        embedding_service = EmbeddingService()
        query_vec = embedding_service.model.encode(["test"])[0].tolist()

        # Search for only prose chunks
        results = service.search(query_vec, limit=10, chunk_types=["prose"])

        assert len(results) > 0
        for result in results:
            assert result.get('chunk_type') == 'prose'

    def test_keyword_search_structure(self):
        """Test that keyword search returns consistent structure."""
        # Create temporary chunks file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            import json
            test_chunks = [
                {
                    "chunk_id": "kw_test_1",
                    "content": "UPF setup and testing procedures",
                    "source_file": "test.md",
                    "chunk_type": "prose",
                    "metadata": {"test": True},
                    "token_count": 10,
                    "line_start": 1
                }
            ]
            json.dump(test_chunks, f)
            chunks_path = f.name

        try:
            service = KeywordSearchService(chunks_path=Path(chunks_path))
            results = service.search("UPF testing", limit=5)

            assert len(results) > 0

            # Verify flat structure (same as semantic search)
            for result in results:
                assert 'chunk_id' in result
                assert 'content' in result
                assert 'source_file' in result
                assert 'chunk_type' in result
                assert 'metadata_json' in result
                assert 'distance' in result
                assert 'entity' not in result  # Must not be nested
        finally:
            os.unlink(chunks_path)

    def test_structure_compatibility_semantic_vs_keyword(self, milvus_with_test_data):
        """CRITICAL: Test that semantic and keyword results have identical structure.

        This prevents the hybrid search bug where incompatible structures caused data loss.
        """
        service, test_chunks = milvus_with_test_data

        # Get semantic results
        embedding_service = EmbeddingService()
        query_vec = embedding_service.model.encode(["test"])[0].tolist()
        semantic_results = service.search(query_vec, limit=1)

        # Get keyword results
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            import json
            json.dump([
                {
                    "chunk_id": c.chunk_id,
                    "content": c.content,
                    "source_file": c.source_file,
                    "chunk_type": c.chunk_type,
                    "metadata": json.loads(c.metadata_json) if c.metadata_json else {},
                    "token_count": c.token_count,
                    "line_start": c.line_start
                }
                for c in test_chunks
            ], f)
            chunks_path = f.name

        try:
            keyword_service = KeywordSearchService(chunks_path=Path(chunks_path))
            keyword_results = keyword_service.search("test", limit=1)

            assert len(semantic_results) > 0
            assert len(keyword_results) > 0

            semantic_keys = set(semantic_results[0].keys())
            keyword_keys = set(keyword_results[0].keys())

            # Both must have the same top-level keys (structure compatibility)
            required_keys = {'chunk_id', 'content', 'source_file', 'chunk_type',
                           'metadata_json', 'distance'}

            assert required_keys.issubset(semantic_keys), \
                f"Semantic missing keys: {required_keys - semantic_keys}"
            assert required_keys.issubset(keyword_keys), \
                f"Keyword missing keys: {required_keys - keyword_keys}"

            print(f"✓ Semantic keys: {sorted(semantic_keys)}")
            print(f"✓ Keyword keys: {sorted(keyword_keys)}")
            print("✓ Structures are compatible for hybrid search")

        finally:
            os.unlink(chunks_path)


@pytest.mark.integration
def test_milvus_hit_object_structure():
    """Document the actual structure of Milvus Hit objects.

    This test exists to detect when Milvus library updates change the Hit structure.
    """
    from pymilvus import MilvusClient

    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name

    try:
        client = MilvusClient(uri=db_path)

        # Create minimal collection
        from pymilvus import DataType
        schema = client.create_schema()
        schema.add_field("id", DataType.VARCHAR, max_length=64, is_primary=True)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=128)
        schema.add_field("content", DataType.VARCHAR, max_length=1000)

        index_params = client.prepare_index_params()
        index_params.add_index("vector", index_type="FLAT", metric_type="L2")

        client.create_collection("test", schema=schema, index_params=index_params)

        # Insert test data
        client.insert("test", [{
            "id": "test1",
            "vector": [0.1] * 128,
            "content": "test content"
        }])

        # Search and inspect actual Hit structure
        results = client.search(
            "test",
            data=[[0.1] * 128],
            limit=1,
            output_fields=["id", "content"]
        )

        assert len(results[0]) > 0, "Should get results"
        hit = results[0][0]

        # Document the actual structure
        print(f"\nActual Hit type: {type(hit)}")
        print(f"Is dict: {isinstance(hit, dict)}")
        print(f"Has 'entity' attr: {hasattr(hit, 'entity')}")
        print(f"Has 'distance' attr: {hasattr(hit, 'distance')}")

        # This documents what we expect - if this fails, Milvus changed!
        # Hit behavior varies by environment:
        # - Python 3.11/older: isinstance(hit, dict) returns True (dict subclass)
        # - Python 3.14/newer: isinstance(hit, dict) returns False (Hit object)
        # In BOTH cases, Hit has entity and distance attributes
        assert hasattr(hit, 'entity'), "Hit should have entity attribute"
        assert hasattr(hit, 'distance'), "Hit should have distance attribute"

        # The critical check: Hit should NOT have chunk_id at top level (it's in entity)
        # This is what our flattening logic depends on
        if isinstance(hit, dict):
            assert 'chunk_id' not in hit or hit.get('chunk_id') is None, \
                "Hit dict should not have chunk_id at top level (should be in entity)"

        # Verify entity structure
        entity = hit.entity
        print(f"Entity type: {type(entity)}")
        print(f"Entity keys: {list(entity.keys())}")

        # Entity should have the actual data
        assert 'id' in entity or 'chunk_id' in entity, "Entity should contain id or chunk_id"

    finally:
        try:
            os.unlink(db_path)
        except:
            pass


if __name__ == '__main__':
    # Run integration tests only
    pytest.main([__file__, '-v', '-m', 'integration'])
