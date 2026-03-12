"""Integration tests for chunk serialization."""

import tempfile
import json
from pathlib import Path
from opencrane.rag.services.chunk_serializer import ChunkSerializer
from opencrane.shared.models.chunk import Chunk


class TestChunkSerializationIntegration:
    """Integration tests for chunk serialization."""

    def test_serialize_deserialize_chunks(self):
        """Test round-trip serialization of chunks."""
        chunks = [
            Chunk(
                content="First chunk content.",
                source_file="file1.md",
                chunk_type="prose",
                metadata={},
                token_count=4
            ),
            Chunk(
                content="Second chunk content.",
                source_file="file2.md",
                chunk_type="prose",
                metadata={},
                token_count=4
            )
        ]

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = Path(f.name)

        try:
            # Serialize
            ChunkSerializer.serialize_chunks(chunks, temp_path)

            # Deserialize
            loaded_chunks = ChunkSerializer.deserialize_chunks(temp_path)

            # Verify
            assert len(loaded_chunks) == 2
            assert loaded_chunks[0].content == "First chunk content."
            assert loaded_chunks[1].content == "Second chunk content."

            # Check deterministic ordering
            assert loaded_chunks[0].source_file == "file1.md"
            assert loaded_chunks[1].source_file == "file2.md"

        finally:
            temp_path.unlink()

    def test_deterministic_output(self):
        """Test that serialization produces deterministic output."""
        chunks = [
            Chunk(
                content="Content B",
                source_file="file2.md",
                chunk_type="prose",
                metadata={},
                token_count=2
            ),
            Chunk(
                content="Content A",
                source_file="file1.md",
                chunk_type="prose",
                metadata={},
                token_count=2
            )
        ]

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f1, \
             tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f2:

            temp_path1 = Path(f1.name)
            temp_path2 = Path(f2.name)

        try:
            # Serialize twice
            ChunkSerializer.serialize_chunks(chunks, temp_path1)
            ChunkSerializer.serialize_chunks(chunks, temp_path2)

            # Read contents
            with open(temp_path1, 'r') as f:
                content1 = f.read()
            with open(temp_path2, 'r') as f:
                content2 = f.read()

            assert content1 == content2

        finally:
            temp_path1.unlink()
            temp_path2.unlink()