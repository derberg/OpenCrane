"""Test for remaining edge cases to achieve 100% coverage."""

from pathlib import Path
from unittest.mock import Mock
from opencrane.rag.services.prose_chunker import ProseChunkingStrategy
from opencrane.rag.services.file_processor import FileProcessor
import logging


def test_prose_url_heading_with_title():
    """Test prose chunker handles URL heading with a title."""
    strategy = ProseChunkingStrategy()
    
    mock_node = Mock()
    # Heading with URL and actual title
    mock_node.text = "# https://github.com/org/repo/file.md Some Title\n\nContent here."
    mock_node.node_type = 'text'
    mock_node.source_url = None
    
    # Just ensure it doesn't crash and produces chunks
    chunks = strategy.process(mock_node, Path('test.md'))
    assert len(chunks) >= 1


def test_file_processor_standalone_url_marker(caplog):
    """Test file processor handles standalone URL marker (H3 without title)."""
    processor = FileProcessor()
    
    # Create a test node for standalone URL (boundary marker)
    class MockNode:
        text = "### https://github.com/test/file.md"
        node_type = "heading"
    
    # Capture debug log to ensure the debug line executes
    with caplog.at_level(logging.DEBUG):
        processor._update_header_context(MockNode())
    
    # Check that the debug message was logged
    assert any("Filtered out H3 boundary marker" in record.message for record in caplog.records)

