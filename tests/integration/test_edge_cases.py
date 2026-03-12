"""Tests for new test fixtures and edge cases."""

import pytest
from pathlib import Path
from opencrane.rag.services.file_processor import process_file
from opencrane.shared.utils.token_counter import get_token_count


class TestEdgeCaseFixtures:
    """Test edge case fixtures."""

    def test_empty_file(self):
        """Test processing an empty file."""
        test_file = Path(__file__).parent.parent / "fixtures" / "edge-cases" / "empty.md"
        chunks = process_file(test_file)
        # Empty files should produce no chunks
        assert len(chunks) == 0

    def test_only_headers_file(self):
        """Test file with only headers and no content."""
        test_file = Path(__file__).parent.parent / "fixtures" / "edge-cases" / "only-headers.md"
        chunks = process_file(test_file)
        # Headers without content may produce minimal chunks
        # The exact behavior depends on strategy implementation
        assert isinstance(chunks, list)

    def test_deeply_nested_file(self):
        """Test file with deeply nested headers."""
        test_file = Path(__file__).parent.parent / "fixtures" / "edge-cases" / "deeply-nested.md"
        chunks = process_file(test_file)
        assert len(chunks) > 0

    def test_malformed_yaml(self):
        """Test handling of malformed YAML."""
        test_file = Path(__file__).parent.parent / "fixtures" / "edge-cases" / "malformed.yaml"
        chunks = process_file(test_file)
        # Malformed YAML should fail gracefully
        # It might produce no chunks or fall back to prose
        assert isinstance(chunks, list)

    def test_large_crd(self):
        """Test processing large CRD that should be split."""
        test_file = Path(__file__).parent.parent / "fixtures" / "large-crd.yaml"
        chunks = process_file(test_file)
        assert len(chunks) > 0
        
        # Calculate total tokens
        total_tokens = sum(c.token_count for c in chunks)
        assert total_tokens > 500  # Should be substantial

    def test_multi_doc_yaml(self):
        """Test processing multi-document YAML."""
        test_file = Path(__file__).parent.parent / "fixtures" / "multi-doc.yaml"
        chunks = process_file(test_file)
        assert len(chunks) >= 3  # Should have at least 3 documents
        
        # All should be YAML type (yaml_content for non-CRD, crd_definition for actual CRDs)
        yaml_chunks = [c for c in chunks if c.chunk_type in ["yaml_content", "crd_definition"]]
        assert len(yaml_chunks) > 0

    def test_code_sample(self):
        """Test processing file with code blocks."""
        test_file = Path(__file__).parent.parent / "fixtures" / "code-sample.md"
        chunks = process_file(test_file)
        assert len(chunks) > 0
        
        # Should have code chunks
        code_chunks = [c for c in chunks if c.chunk_type == "code_snippet"]
        assert len(code_chunks) > 0
        
        # Check that languages are captured
        languages = [c.metadata.get("language") for c in code_chunks]
        assert "python" in languages or "unknown" in languages


class TestChunkRefreshTokenCount:
    """Test the refresh_token_count method."""

    def test_refresh_token_count(self):
        """Test that refresh_token_count recalculates tokens."""
        from opencrane.shared.models.chunk import Chunk
        
        content = "This is a test chunk with some content."
        chunk = Chunk(
            content=content,
            source_file="test.md",
            chunk_type="prose",
            metadata={},
            token_count=999  # Intentionally wrong
        )
        
        # Refresh should fix it
        chunk.refresh_token_count()
        expected_tokens = get_token_count(content)
        assert chunk.token_count == expected_tokens
        assert chunk.token_count != 999


class TestLineStartField:
    """Test the line_start field for deterministic ordering."""

    def test_chunk_with_line_start(self):
        """Test creating a chunk with line_start."""
        from opencrane.shared.models.chunk import Chunk
        
        chunk = Chunk(
            content="Test content",
            source_file="test.md",
            chunk_type="prose",
            metadata={},
            token_count=5,
            line_start=42
        )
        
        assert chunk.line_start == 42

    def test_chunk_without_line_start(self):
        """Test that line_start is optional."""
        from opencrane.shared.models.chunk import Chunk
        
        chunk = Chunk(
            content="Test content",
            source_file="test.md",
            chunk_type="prose",
            metadata={},
            token_count=5
        )
        
        assert chunk.line_start is None

    def test_serialization_ordering_with_line_start(self):
        """Test that serialization uses line_start for ordering."""
        from opencrane.shared.models.chunk import Chunk
        from opencrane.rag.services.chunk_serializer import ChunkSerializer
        import tempfile
        import json
        
        chunks = [
            Chunk(
                content="Third",
                source_file="test.md",
                chunk_type="prose",
                metadata={},
                token_count=1,
                line_start=30
            ),
            Chunk(
                content="First",
                source_file="test.md",
                chunk_type="prose",
                metadata={},
                token_count=1,
                line_start=10
            ),
            Chunk(
                content="Second",
                source_file="test.md",
                chunk_type="prose",
                metadata={},
                token_count=1,
                line_start=20
            ),
        ]
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            output_path = Path(f.name)
        
        try:
            ChunkSerializer.serialize_chunks(chunks, output_path)
            
            # Read back and check order
            with open(output_path) as f:
                data = json.load(f)
            
            # Should be sorted by line_start
            assert data[0]["content"] == "First"
            assert data[1]["content"] == "Second"
            assert data[2]["content"] == "Third"
        finally:
            output_path.unlink()
