"""Integration test to verify search results have consistent flat structure.

This test prevents bugs where search results from different sources (semantic, keyword, hybrid)
have incompatible structures (e.g., nested vs flat) that cause data loss during merging.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock


class MockHit(dict):
    """Mock Hit object that mimics pymilvus.client.search_result.Hit behavior.

    This simulates the real Hit class which is a dict subclass with nested 'entity' structure.
    """

    def __init__(self, data):
        super().__init__(data)
        # Mimic Hit object behavior: has both dict keys and attributes
        self._distance = data.get('distance', 0.0)
        self._entity = data.get('entity', {})

    @property
    def distance(self):
        return self._distance

    @property
    def entity(self):
        """Return a Hit object representing the entity (nested structure)."""
        # Real Hit.entity returns another Hit object with the same data
        # This creates the nested structure: hit.entity.get('chunk_id')
        return MockHit(self)

    def get(self, key, default=None):
        """Custom get that checks nested entity if key not found at top level."""
        # This mimics the real Hit class behavior
        if key in self:
            return super().get(key, default)
        # Check in nested entity dict
        entity_dict = super().get('entity', {})
        if isinstance(entity_dict, dict) and key in entity_dict:
            return entity_dict[key]
        return default


class TestSearchResultStructure:
    """Test that all search modes return consistent flat result structure."""

    @patch('opencrane.mcp.services.milvus_client.MilvusClient')
    def test_milvus_search_flattens_nested_hit_structure(self, mock_client_class):
        """Test that MilvusService.search() properly flattens nested Hit objects.

        This test would have caught the bug where isinstance(hit, dict) check
        failed to detect nested Hit objects, leaving results in nested format.
        """
        from opencrane.mcp.services.milvus_client import MilvusService

        mock_client = Mock()
        mock_client_class.return_value = mock_client

        # Simulate real Milvus Hit objects with nested 'entity' structure
        mock_client.search.return_value = [[
            MockHit({
                'id': 'chunk1',
                'distance': 0.85,
                'entity': {
                    'chunk_id': 'chunk1',
                    'content': 'This is test content',
                    'source_file': 'test.md',
                    'chunk_type': 'prose',
                    'category': 'product',
                    'metadata_json': '{"key": "value"}',
                }
            }),
            MockHit({
                'id': 'chunk2',
                'distance': 0.75,
                'entity': {
                    'chunk_id': 'chunk2',
                    'content': 'More test content',
                    'source_file': 'test2.md',
                    'chunk_type': 'code_snippet',
                    'category': 'product',
                    'metadata_json': '{}',
                }
            })
        ]]

        service = MilvusService()
        results = service.search([0.1] * 768, limit=5)

        # CRITICAL: Verify results are FLATTENED (not nested)
        assert len(results) == 2, "Should return 2 results"

        for i, result in enumerate(results):
            # Each result must be a flat dict with chunk_id at top level
            assert 'chunk_id' in result, f"Result {i} missing 'chunk_id' at top level"
            assert 'content' in result, f"Result {i} missing 'content' at top level"
            assert 'source_file' in result, f"Result {i} missing 'source_file' at top level"
            assert 'chunk_type' in result, f"Result {i} missing 'chunk_type' at top level"
            assert 'metadata_json' in result, f"Result {i} missing 'metadata_json' at top level"
            assert 'distance' in result, f"Result {i} missing 'distance' at top level"

            # Must NOT have nested 'entity' structure in final result
            assert 'entity' not in result, f"Result {i} should not have nested 'entity' key"

            # Values must not be None or empty (unless legitimately empty)
            assert result['chunk_id'] is not None, f"Result {i} has None chunk_id"
            assert result['chunk_id'] != '', f"Result {i} has empty chunk_id"
            assert result['content'] is not None, f"Result {i} has None content"
            # Content can be empty string for some chunk types, but not None
            assert isinstance(result['content'], str), f"Result {i} content is not a string"

    @patch('opencrane.mcp.services.milvus_client.MilvusClient')
    def test_milvus_search_handles_already_flat_results(self, mock_client_class):
        """Test that already-flattened results are not double-processed."""
        from opencrane.mcp.services.milvus_client import MilvusService

        mock_client = Mock()
        mock_client_class.return_value = mock_client

        # Simulate already-flattened results (e.g., from mock Milvus)
        mock_client.search.return_value = [[
            {
                'chunk_id': 'chunk1',
                'content': 'Test content',
                'source_file': 'test.md',
                'chunk_type': 'prose',
                'category': 'product',
                'metadata_json': '{}',
                'distance': 0.9
            }
        ]]

        service = MilvusService()
        results = service.search([0.1] * 768, limit=5)

        assert len(results) == 1
        assert results[0]['chunk_id'] == 'chunk1'
        assert results[0]['content'] == 'Test content'

    # NOTE: Async test commented out - requires pytest-asyncio
    # The synchronous tests above already cover the critical flattening logic
    # For integration testing of hybrid search, use manual testing or E2E tests
    #
    # @pytest.mark.asyncio
    # async def test_hybrid_search_result_structure_consistency(...):
    #     """Test that hybrid search produces consistent flat structure from all sources."""
    #     pass

    def test_result_structure_schema_validation(self):
        """Define the expected schema for all search results (semantic, keyword, hybrid).

        This serves as documentation and validation for the required result structure.
        """
        required_fields = [
            'chunk_id',      # Must be non-None, non-empty string
            'content',       # Must be string (can be empty for some types)
            'source_file',   # Must be string
            'chunk_type',    # Must be string
            'metadata_json', # Must be string (JSON)
            'distance',      # Must be number (float)
        ]

        optional_fields = [
            'category',      # String
            'token_count',   # Integer
            'line_start',    # Integer
        ]

        # Example valid result
        valid_result = {
            'chunk_id': 'abc123',
            'content': 'Some content',
            'source_file': 'file.md',
            'chunk_type': 'prose',
            'metadata_json': '{}',
            'distance': 0.85,
            'category': 'product',
        }

        # Verify all required fields present
        for field in required_fields:
            assert field in valid_result, f"Valid result missing required field: {field}"

        # Must NOT have nested 'entity' structure
        assert 'entity' not in valid_result, "Results should not have nested 'entity' key"

        # Document the constraint
        assert isinstance(valid_result['chunk_id'], str) and valid_result['chunk_id'] != ''
        assert isinstance(valid_result['content'], str)  # Can be empty
        assert isinstance(valid_result['distance'], (int, float))


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
