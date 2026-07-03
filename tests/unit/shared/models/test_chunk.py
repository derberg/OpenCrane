"""Unit tests for Chunk model."""

import pytest
from pydantic import ValidationError
from opencrane.shared.models.chunk import Chunk


class TestChunk:
    """Test the Chunk Pydantic model."""

    def test_valid_chunk(self):
        """Test creating a valid chunk."""
        chunk = Chunk(
            content="Some content",
            source_file="test.md",
            chunk_type="prose",
            metadata={},
            token_count=10
        )
        assert chunk.content == "Some content"
        assert chunk.token_count == 10

    def test_invalid_empty_content(self):
        """Test that empty content raises validation error."""
        with pytest.raises(ValidationError):
            Chunk(
                content="",
                source_file="test.md",
                chunk_type="prose",
                metadata={},
                token_count=0
            )

    def test_invalid_negative_token_count(self):
        """Test that negative token_count raises validation error."""
        with pytest.raises(ValidationError):
            Chunk(
                content="Content",
                source_file="test.md",
                chunk_type="prose",
                metadata={},
                token_count=-1
            )

    def test_invalid_metadata_shape_prose(self):
        """Test invalid metadata for prose chunk."""
        with pytest.raises(ValidationError):
            Chunk(
                content="Content",
                source_file="test.md",
                chunk_type="prose",
                metadata={"invalid": "field"},
                token_count=10
            )

    def test_optional_root_identity_crd(self):
        """Test that yaml_content chunks can have optional root_identity."""
        # Should work without root_identity (for split large YAML chunks)
        chunk = Chunk(
            content="Content",
            source_file="test.yaml",
            chunk_type="yaml_content",
            metadata={"some": "field"},
            token_count=10
        )
        assert chunk.chunk_type == "yaml_content"
        assert "root_identity" not in chunk.metadata

    def test_table_row_chunk_requires_metadata(self):
        """Test table_row chunk metadata validation."""
        ok = Chunk(chunk_id="x", content="A: a. B: b.", source_file="d.md", chunk_type="table_row",
                   metadata={"table_id": "t1", "columns": ["A", "B"], "row_index": 1,
                             "total_rows": 2, "row_key": "a", "sibling_ids": [], "sibling_previews": ["b"]},
                   token_count=5)
        assert ok.chunk_type == "table_row"
        with pytest.raises(ValidationError):
            Chunk(chunk_id="x", content="c", source_file="d.md", chunk_type="table_row",
                  metadata={"table_id": "t1"}, token_count=1)


def test_table_row_chunk_rejects_non_string_content():
    from opencrane.shared.models.chunk import Chunk
    import pytest
    with pytest.raises(Exception):
        Chunk(chunk_id="x", content={"a": 1}, source_file="d.md", chunk_type="table_row",
              metadata={"table_id": "t1", "columns": ["A"], "row_index": 1, "total_rows": 1,
                        "row_key": "a", "sibling_ids": [], "sibling_previews": []}, token_count=1)