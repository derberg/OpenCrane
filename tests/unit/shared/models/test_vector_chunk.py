"""Unit tests for vector_chunk models."""

import pytest
from opencrane.shared.models.vector_chunk import generate_chunk_id, VectorChunk, EmbeddingRecord
from opencrane.shared.models.chunk import Chunk


class TestVectorChunk:
    """Test cases for vector chunk utilities."""

    def test_generate_chunk_id(self):
        """Test deterministic chunk ID generation."""
        chunk_id = generate_chunk_id("file.md", "prose", 10, "content")
        expected = "file.md\nprose\n10\ncontent"
        import hashlib
        expected_hash = hashlib.sha256(expected.encode()).hexdigest()
        assert chunk_id == expected_hash

    def test_generate_chunk_id_no_line_start(self):
        """Test chunk ID with None line_start."""
        chunk_id = generate_chunk_id("file.md", "code", None, "content")
        expected = "file.md\ncode\n\ncontent"
        import hashlib
        expected_hash = hashlib.sha256(expected.encode()).hexdigest()
        assert chunk_id == expected_hash

    def test_vector_chunk_from_chunk_and_embedding(self):
        """Test creating VectorChunk from Chunk and EmbeddingRecord."""
        chunk = Chunk(
            content="test content",
            source_file="file.md",
            chunk_type="prose",
            metadata={"key": "value"},
            token_count=10,
            line_start=5
        )
        embedding = EmbeddingRecord(
            chunk_index=0,
            chunk_id="some_id",
            vector=[0.1] * 768
        )

        vector_chunk = VectorChunk.from_chunk_and_embedding(chunk, embedding)

        assert vector_chunk.chunk_id == "some_id"
        assert vector_chunk.embedding == [0.1] * 768
        assert vector_chunk.content == "test content"
        assert vector_chunk.source_file == "file.md"
        assert vector_chunk.chunk_type == "prose"
        assert vector_chunk.metadata_json == '{\"key\": \"value\"}'
        assert vector_chunk.token_count == 10
        assert vector_chunk.line_start == 5
        # Non-member chunk: list_id/table_id are absent
        assert vector_chunk.list_id is None
        assert vector_chunk.table_id is None

    def test_vector_chunk_lifts_list_and_table_ids(self):
        """list_id/table_id are lifted out of metadata into dedicated fields."""
        from types import SimpleNamespace

        chunk = SimpleNamespace(
            content="row content",
            source_file="file.md",
            source_name=None,
            chunk_type="table_row",
            metadata={"table_id": "T1", "row_index": 0},
            token_count=3,
            line_start=None,
        )
        embedding = EmbeddingRecord(chunk_index=0, chunk_id="id2", vector=[0.2] * 768)

        vector_chunk = VectorChunk.from_chunk_and_embedding(chunk, embedding)

        assert vector_chunk.table_id == "T1"
        assert vector_chunk.list_id is None