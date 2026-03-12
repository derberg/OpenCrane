"""Unit tests for ChunkValidator."""

import pytest
from pathlib import Path
from opencrane.rag.services.chunk_validator import ChunkValidator
from opencrane.shared.models.chunk import Chunk


class TestChunkValidator:
    """Test cases for chunk validation."""

    def test_validate_valid_chunks(self):
        """Test validation of valid chunks."""
        chunks = [
            Chunk(
                content="This is prose content.",
                source_file="test.md",
                chunk_type="prose",
                metadata={},
                token_count=5
            ),
            Chunk(
                content="apiVersion: v1\nkind: Pod",
                source_file="test.yaml",
                chunk_type="yaml_content",
                metadata={"root_identity": {"apiVersion": "v1", "kind": "Pod", "name": "test", "namespace": None}},
                token_count=8
            ),
            Chunk(
                content={"info": {"title": "Test API"}},
                source_file="test.yaml",
                chunk_type="openapi_spec",
                metadata={
                    "breadcrumb_path": "info",
                    "logical_parent": "root",
                    "neighbor_chunks": [],
                    "openapi_version": "3.0.0",
                    "openapi_element": "info"
                },
                token_count=8
            )
        ]

        errors = ChunkValidator.validate_chunks(chunks)
        assert len(errors) == 0
        assert ChunkValidator.is_rag_ready(chunks)

    def test_validate_invalid_chunks(self):
        """Test validation detects issues."""
        # Create a chunk with wrong token count
        chunk = Chunk(
            content="Some content",
            source_file="test.md",
            chunk_type="prose",
            metadata={},
            token_count=100  # Wrong
        )

        errors = ChunkValidator.validate_chunks([chunk])
        assert len(errors) > 0
        assert "token_count mismatch" in errors[0]
        assert not ChunkValidator.is_rag_ready([chunk])

    def test_token_count_mismatch(self):
        """Test detection of token count mismatch."""
        chunk = Chunk(
            content="Short text",
            source_file="test.md",
            chunk_type="prose",
            metadata={},
            token_count=100  # Wrong count
        )

        errors = ChunkValidator.validate_chunks([chunk])
        assert len(errors) > 0
        assert "token_count mismatch" in errors[0]