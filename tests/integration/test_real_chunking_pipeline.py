"""Integration test for real chunking pipeline with llms-full.txt."""

import json
import pytest
from pathlib import Path
from opencrane.rag.services.file_processor import FileProcessor
from opencrane.rag.services.chunk_serializer import ChunkSerializer


@pytest.fixture
def llms_full_path():
    """Path to real llms-full.txt file."""
    return Path("llmstxt/llms-full.txt")


@pytest.fixture
def output_path(tmp_path):
    """Temporary output path for test chunks."""
    return tmp_path / "test-chunks.json"


def test_real_chunking_pipeline_generates_valid_chunks(llms_full_path, output_path):
    """Test that chunking llms-full.txt produces valid chunks with all required fields."""
    # Skip if llms-full.txt doesn't exist
    if not llms_full_path.exists():
        pytest.skip("llms-full.txt not found - run ./setup.sh --generate-llms first")
    
    # Run the actual chunking pipeline
    processor = FileProcessor()
    chunks = processor.process_file(llms_full_path)
    ChunkSerializer.serialize_chunks(chunks, output_path)
    
    # Verify output file was created
    assert output_path.exists(), "Chunking should create output file"
    
    # Load and validate chunks
    with open(output_path, 'r') as f:
        chunks = json.load(f)
    
    # Should produce at least some chunks
    assert len(chunks) > 0, "Should produce at least one chunk"
    
    # Validate every chunk has required fields
    for i, chunk in enumerate(chunks):
        # Critical: chunk_id must be present and valid
        assert chunk.get("chunk_id") is not None, \
            f"Chunk {i} missing chunk_id"
        assert isinstance(chunk["chunk_id"], str), \
            f"Chunk {i} chunk_id should be string"
        # Deterministic hash-based IDs are 64 characters (SHA-256 hex)
        assert len(chunk["chunk_id"]) == 64, \
            f"Chunk {i} chunk_id should be SHA-256 hash format (64 hex chars)"
        # Verify it's a valid hex string
        try:
            int(chunk["chunk_id"], 16)
        except ValueError:
            raise AssertionError(f"Chunk {i} chunk_id should be valid hexadecimal")
        
        # Required fields
        assert "content" in chunk, f"Chunk {i} missing content"
        assert "source_file" in chunk, f"Chunk {i} missing source_file"
        assert "chunk_type" in chunk, f"Chunk {i} missing chunk_type"
        assert "metadata" in chunk, f"Chunk {i} missing metadata"
        assert "token_count" in chunk, f"Chunk {i} missing token_count"
        
        # Validate chunk_type
        assert chunk["chunk_type"] in [
            "prose", "code_snippet", "crd_definition",
            "openapi_spec", "yaml_content", "json_schema"
        ], f"Chunk {i} has invalid chunk_type: {chunk['chunk_type']}"
        
        # Validate token_count is positive
        assert chunk["token_count"] > 0, \
            f"Chunk {i} should have positive token_count"


def test_real_chunking_produces_diverse_chunk_types(llms_full_path, output_path):
    """Test that chunking produces multiple chunk types (prose, code, etc)."""
    # Skip if llms-full.txt doesn't exist
    if not llms_full_path.exists():
        pytest.skip("llms-full.txt not found - run ./setup.sh --generate-llms first")
    
    # Run the actual chunking pipeline
    processor = FileProcessor()
    chunks = processor.process_file(llms_full_path)
    ChunkSerializer.serialize_chunks(chunks, output_path)
    
    # Load chunks
    with open(output_path, 'r') as f:
        chunks = json.load(f)
    
    # Count chunk types
    chunk_types = {}
    for chunk in chunks:
        chunk_type = chunk["chunk_type"]
        chunk_types[chunk_type] = chunk_types.get(chunk_type, 0) + 1
    
    # Should have at least prose chunks (llms-full.txt has lots of text)
    assert "prose" in chunk_types, "Should produce prose chunks"
    assert chunk_types["prose"] > 0, "Should have at least one prose chunk"
    
    # Most llms-full.txt content is text and code blocks
    assert len(chunk_types) >= 1, "Should produce at least one chunk type"


def test_real_chunking_chunk_ids_are_unique(llms_full_path, output_path):
    """Test that all chunk_ids are unique (no duplicates)."""
    # Skip if llms-full.txt doesn't exist
    if not llms_full_path.exists():
        pytest.skip("llms-full.txt not found - run ./setup.sh --generate-llms first")
    
    # Run the actual chunking pipeline
    processor = FileProcessor()
    chunks = processor.process_file(llms_full_path)
    ChunkSerializer.serialize_chunks(chunks, output_path)
    
    # Load chunks
    with open(output_path, 'r') as f:
        chunks = json.load(f)
    
    # Collect all chunk_ids
    chunk_ids = [chunk["chunk_id"] for chunk in chunks]
    
    # Check for duplicates
    assert len(chunk_ids) == len(set(chunk_ids)), \
        f"Found duplicate chunk_ids: {len(chunk_ids)} total, {len(set(chunk_ids))} unique"
