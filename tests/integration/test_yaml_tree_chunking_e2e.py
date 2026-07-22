"""Integration tests for YAML tree chunking end-to-end."""

import pytest
import json
from pathlib import Path
from opencrane.rag.services.file_processor import FileProcessor
from opencrane.shared.models.chunk import Chunk


class TestYAMLTreeChunkingE2E:
    """End-to-end tests for YAML tree chunking."""
    
    def test_markdown_with_crd_matches_expected_chunks(self):
        """Test that markdown_with_crd.md produces expected chunks via FileProcessor."""
        fixtures_dir = Path(__file__).parent.parent / "fixtures"
        markdown_file = fixtures_dir / "markdown_with_crd.md"

        # Process file through production code path
        processor = FileProcessor()
        all_chunks = processor.process_file(markdown_file)

        # Filter to CRD chunks only
        actual_chunks = [c for c in all_chunks if c.chunk_type == "crd_definition"]

        assert len(actual_chunks) > 0, "No CRD chunks generated from markdown"

        # With granular chunking (token limit 800), large properties are recursively chunked.
        # The fixture has one CRD YAML block (the second block is an SMC resource
        # instance, which produces no crd_definition chunks). spec.config exceeded
        # 800 tokens, so it was split into:
        # - spec.config.logLevel, spec.config.enableMetrics, spec.config.metricsPort,
        #   spec.config.database, spec.config.cache, spec.config.messaging
        # Other properties: spec.replicas, spec.image, spec.storage, spec.networking,
        #   spec.resources, spec.affinity, spec.securityContext, spec.monitoring
        # Total: ~14 unique property paths
        assert len(actual_chunks) >= 10, f"Expected at least 10 chunks with granular chunking, got {len(actual_chunks)}"

        # Each schema path must be chunked exactly once (fenced CRDs used to be
        # chunked twice — standalone YAML item + retained section).
        breadcrumbs = [c.metadata["breadcrumb_path"] for c in actual_chunks]
        assert len(breadcrumbs) == len(set(breadcrumbs)), \
            f"CRD schema paths chunked more than once: {sorted(breadcrumbs)}"

        # Verify required properties are present (either as direct chunks or recursively chunked)
        actual_property_paths = [chunk.metadata["crd_property_path"] for chunk in actual_chunks]

        # These properties should exist directly (not recursively chunked)
        expected_direct_properties = ["replicas", "image", "storage", "networking", "resources", "affinity", "securityContext", "monitoring"]
        for expected_prop in expected_direct_properties:
            expected_path = f"spec.{expected_prop}"
            assert expected_path in actual_property_paths, f"Missing expected property: {expected_path}"

        # spec.config was recursively chunked - verify nested properties exist
        config_nested_properties = ["logLevel", "enableMetrics", "metricsPort", "database"]
        for nested_prop in config_nested_properties:
            nested_path = f"spec.config.{nested_prop}"
            assert nested_path in actual_property_paths, f"Missing nested config property: {nested_path}"

        # Verify each chunk has required structure
        for chunk in actual_chunks:
            assert chunk.chunk_id is not None
            assert chunk.chunk_type == "crd_definition"
            assert isinstance(chunk.content, dict)
            assert "breadcrumb_path" in chunk.metadata
            assert "logical_parent" in chunk.metadata
            assert "neighbor_chunks" in chunk.metadata
            assert "crd_kind" in chunk.metadata
            assert "crd_api_version" in chunk.metadata
            assert "crd_version" in chunk.metadata
            assert "crd_property_path" in chunk.metadata

        # Verify all chunks stay under token limit (with some tolerance)
        for chunk in actual_chunks:
            assert chunk.token_count <= 900, f"Chunk {chunk.metadata['crd_property_path']} exceeds limit: {chunk.token_count} tokens"
    
    def test_crd_chunks_match_fixture_structure(self):
        """Test that generated chunks match expected fixture structure."""
        fixtures_dir = Path(__file__).parent.parent / "fixtures"
        expected_file = fixtures_dir / "expected_crd_chunks.json"
        
        with open(expected_file, "r", encoding="utf-8") as f:
            expected_chunks_raw = json.load(f)
        
        # Validate all fixture chunks through Pydantic model to ensure structure is correct
        for chunk_data in expected_chunks_raw:
            # First check that all required fields are present in the JSON (not relying on defaults)
            required_fields = ["chunk_id", "content", "source_file", "chunk_type", "metadata", "token_count"]
            missing_fields = [field for field in required_fields if field not in chunk_data]
            if missing_fields:
                pytest.fail(f"Fixture chunk missing required fields: {missing_fields}\nChunk: {json.dumps(chunk_data, indent=2)}")
            
            # Then validate through Pydantic model
            try:
                Chunk.model_validate(chunk_data)
            except Exception as e:
                pytest.fail(f"Fixture chunk validation failed: {e}\nChunk: {json.dumps(chunk_data, indent=2)}")
        
        # Verify expected fixture has correct structure
        expected_property_paths = [
            chunk["metadata"]["crd_property_path"]
            for chunk in expected_chunks_raw
        ]
        
        # Should have chunks for top-level spec properties only (database is nested under config)
        expected_properties = ["replicas", "image", "config", "storage", "networking", "resources", "affinity", "securityContext", "monitoring"]
        
        for prop in expected_properties:
            assert any(prop in path for path in expected_property_paths), \
                f"Expected property '{prop}' not found in fixture chunks"
    
    def test_crd_neighbor_relationships_in_fixture(self):
        """Test that fixture chunks have correct neighbor relationships."""
        fixtures_dir = Path(__file__).parent.parent / "fixtures"
        expected_file = fixtures_dir / "expected_crd_chunks.json"
        
        with open(expected_file, "r", encoding="utf-8") as f:
            expected_chunks = json.load(f)
        
        # Build chunk map
        chunk_map = {chunk["chunk_id"]: chunk for chunk in expected_chunks}
        
        # Verify mutual neighbor relationships
        for chunk in expected_chunks:
            neighbor_ids = chunk["metadata"]["neighbor_chunks"]
            for neighbor_id in neighbor_ids:
                # Neighbor should exist
                assert neighbor_id in chunk_map, f"Neighbor {neighbor_id} not found in chunks"
                
                # Neighbor should list this chunk back
                neighbor = chunk_map[neighbor_id]
                neighbor_neighbors = neighbor["metadata"]["neighbor_chunks"]
                assert chunk["chunk_id"] in neighbor_neighbors, \
                    f"Chunk {chunk['chunk_id']} not in neighbor {neighbor_id}'s neighbor list"
    
    def test_markdown_with_openapi_matches_expected_chunks(self):
        """Test that markdown_with_openapi.md produces expected chunks via FileProcessor."""
        fixtures_dir = Path(__file__).parent.parent / "fixtures"
        markdown_file = fixtures_dir / "markdown_with_openapi.md"
        
        # Process file through production code path
        processor = FileProcessor()
        all_chunks = processor.process_file(markdown_file)
        
        # Filter to OpenAPI chunks only
        actual_chunks = [c for c in all_chunks if c.chunk_type == "openapi_spec"]
        
        assert len(actual_chunks) > 0, "No OpenAPI chunks generated from markdown"
        
        # Should have multiple chunks for: info, servers, security, tags, paths (multiple operations), components (schemas, securitySchemes)
        assert len(actual_chunks) > 5, f"Expected multiple chunks from OpenAPI spec, got {len(actual_chunks)}"
        
        # Verify all required top-level elements are present
        openapi_elements = {chunk.metadata["openapi_element"] for chunk in actual_chunks}
        assert "info" in openapi_elements, "Missing info chunk"
        assert "paths" in openapi_elements, "Missing path operation chunks"
        
        # Verify each chunk has required structure
        for chunk in actual_chunks:
            assert chunk.chunk_id is not None
            assert chunk.chunk_type == "openapi_spec"
            assert chunk.content is not None
            assert "breadcrumb_path" in chunk.metadata
            assert "logical_parent" in chunk.metadata
            assert "neighbor_chunks" in chunk.metadata
            assert "openapi_version" in chunk.metadata
            assert "openapi_element" in chunk.metadata
            assert "schema_type" in chunk.metadata
            assert chunk.metadata["schema_type"] == "openapi"
        
        # Verify path operations have endpoint metadata
        path_chunks = [c for c in actual_chunks if c.metadata["openapi_element"] == "paths"]
        assert len(path_chunks) > 0, "No path operation chunks found"
        for path_chunk in path_chunks:
            assert "endpoint_path" in path_chunk.metadata
            assert "http_method" in path_chunk.metadata
        
        # Verify schema components have schema_name metadata
        schema_chunks = [c for c in actual_chunks if c.metadata.get("component_type") == "schemas"]
        for schema_chunk in schema_chunks:
            assert "schema_name" in schema_chunk.metadata
    
    def test_openapi_fixture_structure_validation(self):
        """Test that OpenAPI fixture chunks validate through Pydantic model."""
        fixtures_dir = Path(__file__).parent.parent / "fixtures"
        expected_file = fixtures_dir / "expected_openapi_chunks.json"
        
        with open(expected_file, "r", encoding="utf-8") as f:
            expected_chunks_raw = json.load(f)
        
        # Validate all fixture chunks through Pydantic model to ensure structure is correct
        for chunk_data in expected_chunks_raw:
            # First check that all required fields are present in the JSON (not relying on defaults)
            required_fields = ["chunk_id", "content", "source_file", "chunk_type", "metadata", "token_count"]
            missing_fields = [field for field in required_fields if field not in chunk_data]
            if missing_fields:
                pytest.fail(f"OpenAPI fixture chunk missing required fields: {missing_fields}\nChunk: {json.dumps(chunk_data, indent=2)}")
            
            # Then validate through Pydantic model
            try:
                Chunk.model_validate(chunk_data)
            except Exception as e:
                pytest.fail(f"OpenAPI fixture chunk validation failed: {e}\nChunk: {json.dumps(chunk_data, indent=2)}")

    def test_markdown_with_json_schema_matches_expected_chunks(self):
        """Test that markdown_with_json_schema.md produces expected chunks via FileProcessor."""
        fixtures_dir = Path(__file__).parent.parent / "fixtures"
        markdown_file = fixtures_dir / "markdown_with_json_schema.md"

        # Process file through production code path
        processor = FileProcessor()
        all_chunks = processor.process_file(markdown_file)

        # Filter to JSON Schema chunks only
        actual_chunks = [c for c in all_chunks if c.chunk_type == "json_schema"]

        assert len(actual_chunks) > 0, "No JSON Schema chunks generated from markdown"

        # Should have chunks for: root, properties (id, username, email, profile, roles, metadata), $defs (address, phoneNumber)
        # Root: 1, Properties: 6, Definitions: 2 = 9 total
        assert len(actual_chunks) >= 8, f"Expected at least 8 chunks (properties + definitions), got {len(actual_chunks)}"

        # Verify all required properties are present
        expected_properties = ["id", "username", "email", "profile", "roles", "metadata"]
        actual_property_names = [
            chunk.metadata.get("property_name")
            for chunk in actual_chunks
            if chunk.metadata.get("schema_element") == "properties"
        ]

        for expected_prop in expected_properties:
            assert expected_prop in actual_property_names, f"Missing expected property: {expected_prop}"

        # Verify definitions are present
        expected_defs = ["address", "phoneNumber"]
        actual_def_names = [
            chunk.metadata.get("definition_name")
            for chunk in actual_chunks
            if chunk.metadata.get("schema_element") == "definitions"
        ]

        for expected_def in expected_defs:
            assert expected_def in actual_def_names, f"Missing expected definition: {expected_def}"

        # Verify each chunk has required structure
        for chunk in actual_chunks:
            assert chunk.chunk_id is not None
            assert chunk.chunk_type == "json_schema"
            assert isinstance(chunk.content, dict)
            assert "breadcrumb_path" in chunk.metadata
            assert "logical_parent" in chunk.metadata
            assert "neighbor_chunks" in chunk.metadata
            assert "schema_version" in chunk.metadata
            assert "schema_element" in chunk.metadata
            assert "schema_type" in chunk.metadata
            assert chunk.metadata["schema_type"] == "json_schema"

        # Verify profile property includes nested properties (not as separate chunks)
        profile_chunk = next(
            (c for c in actual_chunks if c.metadata.get("property_name") == "profile"),
            None
        )
        assert profile_chunk is not None
        assert "properties" in profile_chunk.content, "Profile should have nested properties"

    def test_json_schema_fixture_structure_validation(self):
        """Test that JSON Schema fixture chunks validate through Pydantic model."""
        fixtures_dir = Path(__file__).parent.parent / "fixtures"
        expected_file = fixtures_dir / "expected_json_schema_chunks.json"

        with open(expected_file, "r", encoding="utf-8") as f:
            expected_chunks_raw = json.load(f)

        # Validate all fixture chunks through Pydantic model to ensure structure is correct
        for chunk_data in expected_chunks_raw:
            # First check that all required fields are present in the JSON (not relying on defaults)
            required_fields = ["chunk_id", "content", "source_file", "chunk_type", "metadata", "token_count"]
            missing_fields = [field for field in required_fields if field not in chunk_data]
            if missing_fields:
                pytest.fail(f"JSON Schema fixture chunk missing required fields: {missing_fields}\nChunk: {json.dumps(chunk_data, indent=2)}")

            # Then validate through Pydantic model
            try:
                Chunk.model_validate(chunk_data)
            except Exception as e:
                pytest.fail(f"JSON Schema fixture chunk validation failed: {e}\nChunk: {json.dumps(chunk_data, indent=2)}")

    def test_json_schema_neighbor_relationships_in_fixture(self):
        """Test that JSON Schema fixture chunks have correct neighbor relationships."""
        fixtures_dir = Path(__file__).parent.parent / "fixtures"
        expected_file = fixtures_dir / "expected_json_schema_chunks.json"

        with open(expected_file, "r", encoding="utf-8") as f:
            expected_chunks = json.load(f)

        # Build chunk map
        chunk_map = {chunk["chunk_id"]: chunk for chunk in expected_chunks}

        # Verify mutual neighbor relationships
        for chunk in expected_chunks:
            neighbor_ids = chunk["metadata"]["neighbor_chunks"]
            for neighbor_id in neighbor_ids:
                # Neighbor should exist
                assert neighbor_id in chunk_map, f"Neighbor {neighbor_id} not found in chunks"

                # Neighbor should list this chunk back
                neighbor = chunk_map[neighbor_id]
                neighbor_neighbors = neighbor["metadata"]["neighbor_chunks"]
                assert chunk["chunk_id"] in neighbor_neighbors, \
                    f"Chunk {chunk['chunk_id']} not in neighbor {neighbor_id}'s neighbor list"

    def test_array_items_recursive_chunking(self):
        """Test that array items with properties are recursively chunked."""
        fixtures_dir = Path(__file__).parent.parent / "fixtures"
        markdown_file = fixtures_dir / "markdown_with_array_items.md"

        # Process file through production code path
        processor = FileProcessor()
        all_chunks = processor.process_file(markdown_file)

        # Filter to JSON Schema chunks only
        actual_chunks = [c for c in all_chunks if c.chunk_type == "json_schema"]

        assert len(actual_chunks) > 0, "No JSON Schema chunks generated from markdown"

        # The volumes array property is large (> 800 tokens) with items containing properties
        # It should be recursively chunked into separate chunks for each item property
        property_chunks = [c for c in actual_chunks if c.metadata.get("schema_element") == "properties"]
        property_paths = [c.metadata.get("property_path") for c in property_chunks]

        # Should NOT have a chunk for "volumes" itself (too large, recursively chunked)
        assert "volumes" not in property_paths, f"Large array 'volumes' should be recursively chunked. Found: {property_paths}"

        # Should have chunks for array item properties (including nested backup)
        expected_item_properties = ["name", "path", "size", "accessMode", "storageClass", "encrypted", "backup"]
        for prop in expected_item_properties:
            item_path = f"volumes.items.{prop}"
            assert item_path in property_paths, f"Missing array item property: {item_path}"

        # Verify all chunks stay under token limit (with tolerance)
        for chunk in property_chunks:
            assert chunk.token_count <= 900, f"Chunk {chunk.metadata.get('property_path')} exceeds limit: {chunk.token_count} tokens"

        # Verify chunks have required structure
        for chunk in actual_chunks:
            assert chunk.chunk_id is not None
            assert chunk.chunk_type == "json_schema"
            assert isinstance(chunk.content, dict)
            assert "breadcrumb_path" in chunk.metadata
            assert "logical_parent" in chunk.metadata
            assert "neighbor_chunks" in chunk.metadata
            assert "schema_version" in chunk.metadata
            assert "schema_element" in chunk.metadata
            assert "schema_type" in chunk.metadata
            assert chunk.metadata["schema_type"] == "json_schema"

    def test_array_items_fixture_validation(self):
        """Test that array items fixture chunks validate through Pydantic model."""
        fixtures_dir = Path(__file__).parent.parent / "fixtures"
        expected_file = fixtures_dir / "expected_array_items_chunks.json"

        with open(expected_file, "r", encoding="utf-8") as f:
            expected_chunks_raw = json.load(f)

        # Validate all fixture chunks through Pydantic model
        for chunk_data in expected_chunks_raw:
            # Check all required fields are present
            required_fields = ["chunk_id", "content", "source_file", "chunk_type", "metadata", "token_count"]
            missing_fields = [field for field in required_fields if field not in chunk_data]
            if missing_fields:
                pytest.fail(f"Array items fixture chunk missing required fields: {missing_fields}\nChunk: {json.dumps(chunk_data, indent=2)}")

            # Validate through Pydantic model
            try:
                Chunk.model_validate(chunk_data)
            except Exception as e:
                pytest.fail(f"Array items fixture chunk validation failed: {e}\nChunk: {json.dumps(chunk_data, indent=2)}")

        # Verify expected structure
        property_chunks = [c for c in expected_chunks_raw if c["metadata"].get("schema_element") == "properties"]
        property_paths = [c["metadata"].get("property_path") for c in property_chunks]

        # All chunks should be from array items (volumes.items.*)
        for path in property_paths:
            assert path.startswith("volumes.items."), f"Expected array item path, got: {path}"

        # Should have 7 item property chunks
        expected_count = 7  # name, path, size, accessMode, storageClass, encrypted, backup
        assert len(property_chunks) == expected_count, f"Expected {expected_count} property chunks, got {len(property_chunks)}"

        # Verify all chunks are under token limit
        for chunk in property_chunks:
            assert chunk["token_count"] <= 900, f"Chunk {chunk['metadata']['property_path']} exceeds limit: {chunk['token_count']} tokens"

