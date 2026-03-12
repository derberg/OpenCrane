"""Tests for deterministic chunk ID generation."""

import pytest
from opencrane.rag.services.utils.chunk_id_generator import generate_chunk_id


def test_generate_chunk_id_deterministic():
    """Same inputs produce same ID."""
    content = "# Test Content\nSome text here."
    source_file = "/path/to/file.md"
    chunk_type = "prose"
    metadata = {}
    
    id1 = generate_chunk_id(content, source_file, chunk_type, metadata)
    id2 = generate_chunk_id(content, source_file, chunk_type, metadata)
    
    assert id1 == id2
    assert len(id1) == 64  # SHA-256 hex is 64 chars


def test_generate_chunk_id_different_content():
    """Different content produces different ID."""
    source_file = "/path/to/file.md"
    chunk_type = "prose"
    metadata = {}
    
    id1 = generate_chunk_id("Content A", source_file, chunk_type, metadata)
    id2 = generate_chunk_id("Content B", source_file, chunk_type, metadata)
    
    assert id1 != id2


def test_generate_chunk_id_different_source_file():
    """Different source file produces different ID."""
    content = "Same content"
    chunk_type = "prose"
    metadata = {}
    
    id1 = generate_chunk_id(content, "/path/to/file1.md", chunk_type, metadata)
    id2 = generate_chunk_id(content, "/path/to/file2.md", chunk_type, metadata)
    
    assert id1 != id2


def test_generate_chunk_id_different_chunk_type():
    """Different chunk type produces different ID."""
    content = "Same content"
    source_file = "/path/to/file.md"
    metadata = {}
    
    id1 = generate_chunk_id(content, source_file, "prose", metadata)
    id2 = generate_chunk_id(content, source_file, "code_snippet", metadata)
    
    assert id1 != id2


def test_generate_chunk_id_with_dict_content():
    """Dict content is serialized deterministically."""
    content = {"key": "value", "nested": {"a": 1, "b": 2}}
    source_file = "/path/to/file.yaml"
    chunk_type = "crd_definition"
    metadata = {"breadcrumb_path": ["spec", "replicas"]}
    
    id1 = generate_chunk_id(content, source_file, chunk_type, metadata)
    id2 = generate_chunk_id(content, source_file, chunk_type, metadata)
    
    assert id1 == id2
    assert len(id1) == 64


def test_generate_chunk_id_dict_key_order_irrelevant():
    """Dict with different key order produces same ID (sorted)."""
    content1 = {"b": 2, "a": 1}
    content2 = {"a": 1, "b": 2}
    source_file = "/path/to/file.yaml"
    chunk_type = "yaml_content"
    
    id1 = generate_chunk_id(content1, source_file, chunk_type)
    id2 = generate_chunk_id(content2, source_file, chunk_type)
    
    assert id1 == id2


def test_generate_chunk_id_with_list_content():
    """List content is serialized deterministically."""
    content = [{"name": "item1"}, {"name": "item2"}]
    source_file = "/path/to/file.yaml"
    chunk_type = "yaml_content"
    
    id1 = generate_chunk_id(content, source_file, chunk_type)
    id2 = generate_chunk_id(content, source_file, chunk_type)
    
    assert id1 == id2


def test_generate_chunk_id_code_with_language():
    """Code chunks with different language get different IDs."""
    content = "print('hello')"
    source_file = "/path/to/file.md"
    chunk_type = "code_snippet"
    
    id1 = generate_chunk_id(content, source_file, chunk_type, {"language": "python"})
    id2 = generate_chunk_id(content, source_file, chunk_type, {"language": "javascript"})
    
    assert id1 != id2


def test_generate_chunk_id_tab_with_tab_value():
    """Tab chunks with different tab_value get different IDs."""
    content = "Install instructions"
    source_file = "/path/to/file.md"
    chunk_type = "prose"
    
    id1 = generate_chunk_id(content, source_file, chunk_type, {"tab_value": "cli"})
    id2 = generate_chunk_id(content, source_file, chunk_type, {"tab_value": "cmc"})
    
    assert id1 != id2


def test_generate_chunk_id_crd_with_breadcrumb():
    """CRD chunks with different breadcrumb get different IDs."""
    content = {"replicas": 3}
    source_file = "/path/to/crd.yaml"
    chunk_type = "crd_definition"
    
    id1 = generate_chunk_id(content, source_file, chunk_type, {"breadcrumb_path": ["spec", "replicas"]})
    id2 = generate_chunk_id(content, source_file, chunk_type, {"breadcrumb_path": ["spec", "config"]})
    
    assert id1 != id2


def test_generate_chunk_id_no_metadata():
    """Works without metadata."""
    content = "Content"
    source_file = "/path/to/file.md"
    chunk_type = "prose"
    
    chunk_id = generate_chunk_id(content, source_file, chunk_type)
    
    assert len(chunk_id) == 64


def test_generate_chunk_id_empty_metadata():
    """Works with empty metadata dict."""
    content = "Content"
    source_file = "/path/to/file.md"
    chunk_type = "prose"
    
    chunk_id = generate_chunk_id(content, source_file, chunk_type, {})
    
    assert len(chunk_id) == 64


def test_generate_chunk_id_unicode_content():
    """Handles unicode content correctly."""
    content = "Hello 世界 🌍"
    source_file = "/path/to/file.md"
    chunk_type = "prose"
    
    id1 = generate_chunk_id(content, source_file, chunk_type)
    id2 = generate_chunk_id(content, source_file, chunk_type)
    
    assert id1 == id2
    assert len(id1) == 64


def test_generate_chunk_id_whitespace_sensitivity():
    """Different whitespace produces different IDs (content-sensitive)."""
    source_file = "/path/to/file.md"
    chunk_type = "prose"
    
    id1 = generate_chunk_id("Content with spaces", source_file, chunk_type)
    id2 = generate_chunk_id("Content  with  spaces", source_file, chunk_type)
    
    assert id1 != id2  # Whitespace matters for content identity


def test_generate_chunk_id_with_non_serializable_content():
    """Handles non-dict/list content types (uses str() fallback)."""
    source_file = "/path/to/file.md"
    chunk_type = "prose"
    
    # Test with number (not dict or list)
    id1 = generate_chunk_id(42, source_file, chunk_type)
    assert len(id1) == 64
    
    # Test with boolean
    id2 = generate_chunk_id(True, source_file, chunk_type)
    assert len(id2) == 64
    
    # Should be deterministic
    id3 = generate_chunk_id(42, source_file, chunk_type)
    assert id1 == id3
