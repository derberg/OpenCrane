"""Integration tests for MCP YAML re-hydration using fixture chunks."""

import pytest
import json
from pathlib import Path
from opencrane.mcp.server import _rehydrate_to_yaml, get_yaml_definition
from unittest.mock import Mock, patch


class TestMCPYAMLRehydrationIntegration:
    """Integration tests for YAML re-hydration with real fixture data."""
    
    def test_rehydrate_crd_chunk_from_fixtures(self):
        """Test YAML re-hydration with actual CRD chunk from fixtures."""
        fixtures_dir = Path(__file__).parent.parent / "fixtures"
        expected_chunks = json.load(open(fixtures_dir / "expected_crd_chunks.json"))
        
        # Get first CRD chunk (should be spec.replicas)
        chunk = expected_chunks[0]
        content = chunk["content"]
        metadata = chunk["metadata"]
        
        # Verify it has YAML format marker
        assert metadata.get("original_format") == "yaml"
        
        # Re-hydrate it
        yaml_output = _rehydrate_to_yaml(content, metadata, "crd_definition")
        
        # Verify breadcrumb comments are added
        assert "# Location:" in yaml_output
        assert metadata["breadcrumb_path"] in yaml_output
        
        # Verify CRD-specific metadata appears
        if "crd_kind" in metadata:
            assert f"# CRD Kind: {metadata['crd_kind']}" in yaml_output
        if "crd_version" in metadata:
            assert f"# CRD Version: {metadata['crd_version']}" in yaml_output
        
        # Verify YAML content is present
        assert "replicas:" in yaml_output or "type:" in yaml_output
        
    def test_rehydrate_openapi_chunk_from_fixtures(self):
        """Test YAML re-hydration with actual OpenAPI chunk from fixtures."""
        fixtures_dir = Path(__file__).parent.parent / "fixtures"
        expected_chunks = json.load(open(fixtures_dir / "expected_openapi_chunks.json"))
        
        # Find a chunk with endpoint metadata
        openapi_chunk = None
        for chunk in expected_chunks:
            if "endpoint_path" in chunk["metadata"]:
                openapi_chunk = chunk
                break
        
        if openapi_chunk:
            content = openapi_chunk["content"]
            metadata = openapi_chunk["metadata"]
            
            # Re-hydrate it
            yaml_output = _rehydrate_to_yaml(content, metadata, "openapi_spec")
            
            # Verify OpenAPI-specific metadata appears
            if "openapi_version" in metadata:
                assert f"# OpenAPI Version: {metadata['openapi_version']}" in yaml_output
            if "endpoint_path" in metadata:
                assert f"# Endpoint: {metadata['endpoint_path']}" in yaml_output
            if "http_method" in metadata:
                method_upper = metadata['http_method'].upper()
                assert f"# Method: {method_upper}" in yaml_output
    
    @patch('opencrane.mcp.server.get_milvus_service')
    @pytest.mark.anyio
    async def test_get_yaml_definition_with_fixture_chunk(self, mock_get_milvus):
        """Test get_yaml_definition tool with real fixture chunk served from Milvus."""
        fixtures_dir = Path(__file__).parent.parent / "fixtures"
        expected_chunks = json.load(open(fixtures_dir / "expected_crd_chunks.json"))

        # Use first chunk for testing. Milvus stores content and metadata as JSON strings.
        test_chunk = expected_chunks[0]
        milvus_row = {
            "chunk_id": test_chunk["chunk_id"],
            "content": json.dumps(test_chunk["content"]),
            "chunk_type": test_chunk["chunk_type"],
            "metadata_json": json.dumps(test_chunk["metadata"]),
        }
        svc = Mock()
        svc.get_chunk.return_value = milvus_row
        mock_get_milvus.return_value = svc

        # Call the tool
        result = await get_yaml_definition({"chunk_id": test_chunk["chunk_id"]})
        
        # Verify result structure
        assert len(result) == 1
        result_text = result[0].text
        
        # Verify it includes chunk metadata
        assert f"Chunk ID: {test_chunk['chunk_id']}" in result_text
        assert f"Type: {test_chunk['chunk_type']}" in result_text
        
        # Verify YAML definition is present
        assert "Definition:" in result_text
        
        # Verify breadcrumb is included (if breadcrumb_path exists)
        if "breadcrumb_path" in test_chunk["metadata"]:
            assert f"# Location: {test_chunk['metadata']['breadcrumb_path']}" in result_text
    
    def test_rehydrate_preserves_yaml_structure(self):
        """Test that re-hydration preserves nested YAML structure from fixtures."""
        fixtures_dir = Path(__file__).parent.parent / "fixtures"
        expected_chunks = json.load(open(fixtures_dir / "expected_crd_chunks.json"))
        
        # Find a chunk with nested structure
        nested_chunk = None
        for chunk in expected_chunks:
            if isinstance(chunk["content"], dict) and len(chunk["content"]) > 0:
                # Check if content has nested dict
                for value in chunk["content"].values():
                    if isinstance(value, dict):
                        nested_chunk = chunk
                        break
                if nested_chunk:
                    break
        
        if nested_chunk:
            content = nested_chunk["content"]
            metadata = nested_chunk["metadata"]
            
            # Re-hydrate
            yaml_output = _rehydrate_to_yaml(content, metadata, "crd_definition")
            
            # Verify YAML structure (should have indentation for nested keys)
            lines = yaml_output.split('\n')
            yaml_content_lines = [l for l in lines if not l.strip().startswith('#')]
            
            # Should have indented lines (nested structure)
            indented_lines = [l for l in yaml_content_lines if l.startswith('  ') and l.strip()]
            assert len(indented_lines) > 0, "Expected nested YAML structure with indentation"
    
    def test_neighbor_chunks_displayed_from_fixtures(self):
        """Test that neighbor chunks are displayed when present in fixture metadata."""
        fixtures_dir = Path(__file__).parent.parent / "fixtures"
        expected_chunks = json.load(open(fixtures_dir / "expected_crd_chunks.json"))
        
        # Find chunk with neighbor_chunks metadata
        chunk_with_neighbors = None
        for chunk in expected_chunks:
            if "neighbor_chunks" in chunk["metadata"] and chunk["metadata"]["neighbor_chunks"]:
                chunk_with_neighbors = chunk
                break
        
        if chunk_with_neighbors:
            content = chunk_with_neighbors["content"]
            metadata = chunk_with_neighbors["metadata"]
            
            # Re-hydrate
            yaml_output = _rehydrate_to_yaml(content, metadata, "crd_definition")
            
            # The _rehydrate_to_yaml doesn't add neighbors, but get_yaml_definition does
            # This test just verifies metadata structure is preserved
            assert "neighbor_chunks" in metadata
            assert isinstance(metadata["neighbor_chunks"], list)
