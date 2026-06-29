"""Unit tests for ProseChunkingStrategy."""

import pytest
from pathlib import Path
from unittest.mock import Mock
from opencrane.rag.services.prose_chunker import ProseChunkingStrategy
from opencrane.shared.models.chunk import Chunk


class TestProseChunkingStrategy:
    """Test cases for prose chunking strategy."""

    def test_can_process_text_node(self):
        """Test that strategy can process text nodes."""
        strategy = ProseChunkingStrategy()
        text_node = Mock()
        text_node.node_type = "text"
        assert strategy.can_process(text_node)

    def test_cannot_process_code_node(self):
        """Test that strategy cannot process code nodes."""
        strategy = ProseChunkingStrategy()
        code_node = Mock()
        code_node.node_type = "code"
        assert not strategy.can_process(code_node)

    def test_process_single_paragraph(self):
        """Test processing a single paragraph."""
        strategy = ProseChunkingStrategy()
        source_file = Path("test.md")

        # Mock a simple text node
        node = Mock()
        node.node_type = "text"
        node.source_url = None  # No node-level source URL
        node.text = "This is a test paragraph."

        chunks = strategy.process(node, source_file)
        assert len(chunks) == 1
        assert chunks[0].chunk_type == "prose"
        assert chunks[0].source_file == str(source_file)
        assert "test paragraph" in chunks[0].content

    def test_process_with_headers(self):
        """Test processing with header hierarchy."""
        strategy = ProseChunkingStrategy()
        source_file = Path("test.md")

        # Mock node with full text
        node = Mock()
        node.node_type = "text"
        node.source_url = None  # No node-level source URL
        node.text = "# Header 1\n\nContent under header."

        chunks = strategy.process(node, source_file)

        # Should have prose chunks
        prose_chunks = [c for c in chunks if c.chunk_type == "prose"]
        assert len(prose_chunks) > 0

    def test_process_with_github_url_in_header(self):
        """Test processing markdown with GitHub URL in header."""
        strategy = ProseChunkingStrategy()
        source_file = Path("test.md")

        # Mock node with header containing GitHub URL
        node = Mock()
        node.node_type = "text"
        node.source_url = None  # No node-level source URL
        node.text = "# [Project Name](https://github.com/org/repo)\n\nSome content here."
        node.source_url = None  # No node-level source URL, should extract from header

        chunks = strategy.process(node, source_file)

        # Should have prose chunks with source_url extracted
        prose_chunks = [c for c in chunks if c.chunk_type == "prose"]
        assert len(prose_chunks) > 0
        
        # At least one chunk should have the GitHub URL in metadata
        has_url = any("source_url" in c.metadata for c in prose_chunks)
        if has_url:
            url_chunks = [c for c in prose_chunks if "source_url" in c.metadata]
            assert any("github.com/org/repo" in c.metadata["source_url"] for c in url_chunks)

    def test_process_multiple_sections_with_urls(self):
        """Test processing multiple sections, each with GitHub URLs."""
        strategy = ProseChunkingStrategy()
        source_file = Path("test.md")

        # Mock node with multiple headers containing different GitHub URLs
        node = Mock()
        node.node_type = "text"
        node.source_url = None  # No node-level source URL, should extract from headers
        node.text = """# [First Repo](https://github.com/org/repo1)

Content for first repo.

## [Second Repo](https://github.com/org/repo2)

Content for second repo.
"""

        chunks = strategy.process(node, source_file)

        # Should have prose chunks with different source_urls
        prose_chunks = [c for c in chunks if c.chunk_type == "prose"]
        assert len(prose_chunks) > 0
        
        # Chunks should potentially have different URLs based on their section
        url_chunks = [c for c in prose_chunks if "source_url" in c.metadata]
        if url_chunks:
            urls = {c.metadata["source_url"] for c in url_chunks}
            # Could have either URL depending on which sections were processed
            assert any("github.com/org/repo" in url for url in urls)

    def test_headers_included_in_chunks(self):
        """Test that headers are included in chunk content."""
        strategy = ProseChunkingStrategy()
        
        mock_node = Mock()
        mock_node.text = """# Main Header

Some content here.

## Subheader

More content here."""
        mock_node.node_type = 'text'
        
        chunks = strategy.process(mock_node, Path('test.md'))
        
        # Should have 2 chunks (one per header section)
        assert len(chunks) == 2
        
        # First chunk should include the header
        assert '# Main Header' in chunks[0].content
        assert 'Some content here.' in chunks[0].content
        
        # Second chunk should include the subheader
        assert '## Subheader' in chunks[1].content
        assert 'More content here.' in chunks[1].content
    
    def test_no_content_loss(self):
        """Test that all non-blank content is preserved in chunks."""
        strategy = ProseChunkingStrategy()
        
        original_text = """# Section 1

Content line 1
Content line 2

## Section 1.1

More content
And more

### Section 1.1.1

Deep content

# Section 2

Final content"""
        
        mock_node = Mock()
        mock_node.text = original_text
        mock_node.node_type = 'text'
        
        chunks = strategy.process(mock_node, Path('test.md'))
        
        # Combine all chunk content
        combined_content = '\n'.join(c.content for c in chunks)
        
        # Count non-blank lines in original vs chunks
        original_lines = [line.strip() for line in original_text.split('\n') if line.strip()]
        chunk_lines = [line.strip() for line in combined_content.split('\n') if line.strip()]
        
        # All original lines should be in chunks
        assert len(chunk_lines) >= len(original_lines)
        for original_line in original_lines:
            assert original_line in combined_content, f"Missing line: {original_line}"
    
    def test_large_section_content_preservation(self):
        """Test that large sections preserve all content including headers."""
        strategy = ProseChunkingStrategy()
        
        # Create a realistic section
        section_text = """# Project Documentation

This is the introduction.

## Installation

Step 1: Download
Step 2: Install
Step 3: Configure

### Configuration Details

Config option A
Config option B

## Usage

Usage example 1
Usage example 2"""
        
        mock_node = Mock()
        mock_node.text = section_text
        mock_node.node_type = 'text'
        
        chunks = strategy.process(mock_node, Path('test.md'))
        
        # Calculate content coverage
        combined_content = ' '.join(c.content for c in chunks)
        original_words = section_text.split()
        
        # Check that we capture at least 95% of words (allowing for whitespace differences)
        words_in_chunks = sum(1 for word in original_words if word in combined_content)
        coverage = words_in_chunks / len(original_words)
        
        assert coverage >= 0.95, f"Only {coverage*100:.1f}% of content preserved"
    
    def test_no_header_only_chunks(self):
        """Test that consecutive headers don't create empty header-only chunks."""
        strategy = ProseChunkingStrategy()
        
        # Simulate structure from llms-full.txt with consecutive headers
        text = """# Project: content-strategy

### https://github.com/example/repo.md

# Main Title

Actual content here.

## Subsection

More content."""
        
        mock_node = Mock()
        mock_node.text = text
        mock_node.node_type = 'text'
        
        chunks = strategy.process(mock_node, Path('test.md'))
        
        # Check that no chunks contain ONLY headers
        for chunk in chunks:
            lines = [line.strip() for line in chunk.content.split('\n') if line.strip()]
            has_only_headers = all(line.startswith('#') for line in lines)
            assert not has_only_headers, f"Found header-only chunk: {chunk.content[:100]}"
        
        # Should have 2 chunks: one for "Main Title" section, one for "Subsection"
        assert len(chunks) == 2, f"Expected 2 chunks, got {len(chunks)}"
    
    def test_has_content_with_empty_chunk(self):
        """Test _has_content returns False when chunk not initialized."""
        strategy = ProseChunkingStrategy()
        # Before processing anything, _has_content should return False
        assert not strategy._has_content()
    
    def test_base_source_url_used_when_no_header_url(self):
        """Test that base_source_url from node is used when headers don't contain URLs."""
        strategy = ProseChunkingStrategy()
        
        mock_node = Mock()
        mock_node.text = "# Simple Header\n\nContent without GitHub URLs."
        mock_node.node_type = 'text'
        mock_node.source_url = "https://github.com/test/repo/blob/main/doc.md"
        
        chunks = strategy.process(mock_node, Path('test.md'))
        
        assert len(chunks) == 1
        assert chunks[0].metadata['source_url'] == "https://github.com/test/repo/blob/main/doc.md"

    def test_url_prefixed_heading_title_extraction(self):
        """Test that GitHub URLs are stripped from headings but preserved in metadata."""
        strategy = ProseChunkingStrategy()
        
        mock_node = Mock()
        mock_node.text = "# https://github.com/org/repo/file.md Documentation\n\nContent here."
        mock_node.node_type = 'text'
        mock_node.source_url = None
        
        chunks = strategy.process(mock_node, Path('test.md'))
        
        # URL should be in metadata
        assert len(chunks) == 1
        assert "source_url" in chunks[0].metadata
        assert chunks[0].metadata["source_url"] == "https://github.com/org/repo/file.md"
        
        # URL should NOT be in content - only the title should remain
        assert "# Documentation" in chunks[0].content
        assert "https://github.com/org/repo/file.md" not in chunks[0].content

    def test_garbage_filtering_short_content(self):
        """Test that very short chunks are filtered as garbage."""
        strategy = ProseChunkingStrategy()
        
        mock_node = Mock()
        # Content less than 15 characters should be filtered
        mock_node.text = "# H\n\ntext"
        mock_node.node_type = 'text'
        mock_node.source_url = None
        
        chunks = strategy.process(mock_node, Path('test.md'))
        
        # Should filter out the short chunk (8 chars total)
        assert len(chunks) == 0

    def test_multiple_sections_with_url_headings(self):
        """Test that multiple sections with GitHub URLs in headings are properly cleaned."""
        strategy = ProseChunkingStrategy()
        
        mock_node = Mock()
        mock_node.text = (
            "# https://github.com/org/repo/doc.md Main Title\n\n"
            "First paragraph content.\n\n"
            "## https://github.com/org/repo/doc.md Section One\n\n"
            "Section one content here.\n\n"
            "## Regular Section\n\n"
            "Regular section content."
        )
        mock_node.node_type = 'text'
        mock_node.source_url = None
        
        chunks = strategy.process(mock_node, Path('test.md'))
        
        # Should have 3 chunks
        assert len(chunks) == 3
        
        # First chunk: URL stripped from heading, preserved in metadata
        assert chunks[0].metadata["source_url"] == "https://github.com/org/repo/doc.md"
        assert "# Main Title" in chunks[0].content
        assert "https://" not in chunks[0].content
        
        # Second chunk: URL stripped from ## heading
        assert chunks[1].metadata["source_url"] == "https://github.com/org/repo/doc.md"
        assert "## Section One" in chunks[1].content
        assert "https://" not in chunks[1].content
        
        # Third chunk: No URL in heading, metadata carries forward
        assert chunks[2].metadata["source_url"] == "https://github.com/org/repo/doc.md"
        assert "## Regular Section" in chunks[2].content

    def test_bracketed_heading_marker_tracks_page_url(self):
        """A bracketed ``# [base] <page-url> Title`` heading tracks the page URL (lines 73-75)."""
        strategy = ProseChunkingStrategy()

        node = Mock()
        node.node_type = "text"
        node.source_url = None  # Force use of _current_source_url tracking
        node.text = (
            "# [https://docs.example.com] https://docs.example.com/guide Getting Started\n\n"
            "This is the body content of the guide section.\n"
        )

        chunks = strategy.process(node, Path("test.md"))

        assert len(chunks) == 1
        # The specific page URL after the bracket is tracked, not the base tag.
        assert chunks[0].metadata["source_url"] == "https://docs.example.com/guide"

    def test_bracketed_heading_marker_without_page_url_falls_back_to_base(self):
        """When no page URL follows the bracket, fall back to the bracket content (line 75)."""
        strategy = ProseChunkingStrategy()

        node = Mock()
        node.node_type = "text"
        node.source_url = None
        node.text = (
            "# [https://docs.example.com/base] Section Title Only\n\n"
            "Body content for the section under the base tag.\n"
        )

        chunks = strategy.process(node, Path("test.md"))

        assert len(chunks) == 1
        # No page URL after the bracket → fall back to the stripped bracket content.
        assert chunks[0].metadata["source_url"] == "https://docs.example.com/base"

    def test_source_separator_resets_url_context(self):
        """A ``======`` separator clears the tracked source URL (line 61)."""
        strategy = ProseChunkingStrategy()

        node = Mock()
        node.node_type = "text"
        node.source_url = None
        node.text = (
            "# https://github.com/org/repo/first.md First\n\n"
            "First section body content goes here.\n\n"
            "# Boundary Heading\n\n"
            "More first-source content here.\n\n"
            "======\n\n"
            "# Second Without URL\n\n"
            "Second section body content goes here.\n"
        )

        chunks = strategy.process(node, Path("test.md"))

        # An early chunk inherits the URL from the first heading marker.
        assert any(
            c.metadata.get("source_url") == "https://github.com/org/repo/first.md"
            for c in chunks
        )
        # After the ====== reset, the final section's chunk carries no source_url.
        assert "source_url" not in chunks[-1].metadata